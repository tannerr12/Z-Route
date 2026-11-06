#!/usr/bin/env python3
"""Read-only Z-Route world-map capture decoder.

Usage:
    python zroute_map_decoder.py zroute_map_test5pcapng.pcapng
    python zroute_map_decoder.py zroute_map_test*.pcapng --output players.csv

Decodes the observed TCP/9929 message envelope and WorldMapViewS2C protobuf
payloads from an *existing* Wireshark PCAPNG capture. Does NOT connect to any
server, send gameplay commands, read credentials, or alter BlueStacks.

The decoded map objects are ONLY the bases observed within the captures; this
is NOT a complete inventory of the game server. The game format is unofficial
and may change. Captured files can contain private gameplay/account data; keep
both PCAPNG files and CSV output private.

Python 3.9+, standard library only.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import socket
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

MAGIC = b"\x70\xa3"
TCP_PORT = 9929
GZIP_HEADER = bytes.fromhex("1f8b08000000000000ff")


def read_packets(path: Path):
    """Extract TCP application-data segments from Ethernet/IPv4 PCAPNG.

    Handles ordinary Wireshark captures with Enhanced Packet Blocks. Other
    link-layer formats and IPv6 are not supported by this small standalone tool.
    """
    content = path.read_bytes()
    pos = 0
    timestamp_scales = []
    start_time = None
    while pos + 12 <= len(content):
        kind, size = struct.unpack_from('<II', content, pos)
        if size < 12 or pos + size > len(content):
            raise ValueError('Damaged PCAPNG block at offset %d' % pos)
        if kind == 1:  # Interface Description Block
            scale = 1_000_000
            opt = pos + 16
            while opt + 4 <= pos + size - 4:
                key, length = struct.unpack_from('<HH', content, opt)
                if key == 0:
                    break
                if key == 9 and length:
                    value = content[opt + 4]
                    scale = 2 ** (value & 127) if value & 128 else 10 ** value
                opt += 4 + ((length + 3) & ~3)
            timestamp_scales.append(scale)
        elif kind == 6:  # Enhanced Packet Block
            interface, high, low, original_length, _ = struct.unpack_from('<IIIII', content, pos + 8)
            scale = timestamp_scales[interface] if interface < len(timestamp_scales) else 1_000_000
            moment = ((high << 32) | low) / scale
            if start_time is None:
                start_time = moment
            frame = content[pos + 28:pos + 28 + original_length]
            if len(frame) < 54 or frame[12:14] != b'\x08\x00':
                pos += size
                continue
            ip = frame[14:]
            header_size = (ip[0] & 15) * 4
            if ip[9] != 6 or len(ip) < header_size + 20:
                pos += size
                continue
            source = socket.inet_ntoa(ip[12:16]); destination = socket.inet_ntoa(ip[16:20])
            length = struct.unpack_from('!H', ip, 2)[0]
            tcp = ip[header_size:length]
            if len(tcp) < 20:
                pos += size
                continue
            src_port, dst_port, sequence = struct.unpack_from('!HHI', tcp)
            hlen = (tcp[12] >> 4) * 4
            if hlen < 20 or hlen > len(tcp):
                pos += size
                continue
            body = tcp[hlen:]
            if body and TCP_PORT in (src_port, dst_port):
                yield (source, src_port, destination, dst_port), sequence, moment - start_time, body
        pos += size


def application_messages(path: Path):
    """Parse received map messages from contiguous TCP byte runs.

    Rolling dumpcap files often start or end in the middle of an application
    message. One missing packet must not discard every subsequent message:
    skip the gap, then resynchronize on a validated message envelope.
    """
    segments = defaultdict(list)
    for key, sequence, when, payload in read_packets(Path(path)):
        if key[1] == TCP_PORT:
            segments[key].append((sequence, when, payload))

    for key, parts in segments.items():
        parts.sort(key=lambda item: item[0])
        runs = []
        start = end = None
        buf = bytearray()
        timestamps = []

        def finish_run():
            if buf:
                runs.append((start, bytes(buf), list(timestamps)))

        for seq, when, payload in parts:
            if start is None or seq > end:
                finish_run()
                start, end = seq, seq
                buf = bytearray()
                timestamps = []
            overlap = end - seq
            if overlap >= len(payload):
                continue  # duplicate/retransmitted segment
            piece = payload[max(0, overlap):]
            timestamps.append((end, when))
            buf.extend(piece)
            end += len(piece)
        finish_run()

        for start, stream, times in runs:
            i = 0
            while i + 10 <= len(stream):
                at = stream.find(MAGIC, i)
                if at < 0 or at + 10 > len(stream):
                    break
                n = struct.unpack_from('>H', stream, at + 4)[0]
                if not 1 <= n <= 100 or at + 10 + n > len(stream):
                    i = at + 1
                    continue
                try:
                    name = stream[at + 6:at + 6 + n].decode('ascii')
                except UnicodeDecodeError:
                    i = at + 1
                    continue
                if not name or not all(ch.isalnum() or ch == '_' for ch in name):
                    i = at + 1
                    continue
                size = struct.unpack_from('>I', stream, at + 6 + n)[0]
                finish = at + 10 + n + size
                if size > 16_000_000 or finish > len(stream):
                    i = at + 1
                    continue
                if name in ('WorldMapViewS2C', 'WorldMapViewUpdateS2C'):
                    seq = start + at
                    timestamp = next((t for pkt_seq, t in reversed(times)
                                      if pkt_seq <= seq), None)
                    yield name, timestamp, bytes(stream[at + 10 + n:finish])
                i = finish


def protobuf_varint(data: bytes, i: int):
    number = 0
    for shift in range(0, 70, 7):
        if i >= len(data):
            raise ValueError('truncated varint')
        byte = data[i]
        i += 1
        number |= (byte & 127) << shift
        if byte < 128:
            return number, i
    raise ValueError('oversized varint')


def protobuf_fields(data: bytes):
    out = []
    i = 0
    while i < len(data):
        tag, i = protobuf_varint(data, i)
        num, wire = tag >> 3, tag & 7
        if num < 1 or num > 1_000_000:
            raise ValueError('invalid protobuf field')
        if wire == 0:
            value, i = protobuf_varint(data, i)
        elif wire == 1:
            if i + 8 > len(data): raise ValueError('truncated fixed64')
            value = int.from_bytes(data[i:i + 8], 'little')
            i += 8
        elif wire == 2:
            length, i = protobuf_varint(data, i)
            if length > len(data) - i:
                raise ValueError('truncated length-delimited field')
            value = data[i:i + length]
            i += length
        elif wire == 5:
            if i + 4 > len(data): raise ValueError('truncated fixed32')
            value = int.from_bytes(data[i:i + 4], 'little')
            i += 4
        else:
            raise ValueError('unsupported protobuf wire type')
        out.append((num, wire, value))
    return out


def value(fields, number, wire, default=None):
    return next((v for n, w, v in fields if n == number and w == wire), default)


def map_root(data: bytes):
    """Validate observed map-view top-level fields and map location."""
    fields = protobuf_fields(data)
    if [(n, w) for n, w, _ in fields[:4]] != [(1,0), (2,0), (3,0), (4,2)]:
        raise ValueError('not an observed map-view protobuf')
    location = protobuf_fields(fields[3][2])
    if [(n, w) for n, w, _ in location[:3]] != [(1,0), (2,0), (3,0)]:
        raise ValueError('invalid map location')
    if not 1 <= location[0][2] <= 10000:
        raise ValueError('invalid server')
    return fields


def decode_payload(raw: bytes):
    """Invert the observed per-message byte substitution and decompress if gzip.

    Ciphertext byte = ((plaintext byte + salt) & 255) XOR mask.
    We infer the parameters independently for each message. A valid gzip CRC
    or fully parsed map-root protobuf makes the decoding unambiguous here.
    """
    if not raw:
        raise ValueError('empty map payload')
    # Gzip header bytes 3-8 are all zero; gzip OS byte 9 is 0xff.
    if len(raw) >= 20 and len(set(raw[3:9])) == 1:
        for salt in range(128):
            mask = raw[3] ^ salt
            if all((((c + salt) & 255) ^ mask) == raw[j]
                   for j, c in enumerate(GZIP_HEADER)):
                plain = bytes((((c ^ mask) - salt) & 255) for c in raw)
                try:
                    body = gzip.decompress(plain)  # includes gzip CRC validation
                    map_root(body)
                    return body, 'gzip'
                except (OSError, EOFError, zlib.error, ValueError):
                    continue
    # Smaller map-view messages can be protobuf without gzip.
    # All observed valid map roots start with protobuf tag 0x08.
    candidates = []
    for salt in range(128):
        mask = raw[0] ^ ((8 + salt) & 255)
        plain = bytes((((c ^ mask) - salt) & 255) for c in raw)
        try:
            map_root(plain)
            candidates.append(plain)
        except ValueError:
            continue
    if len(candidates) == 1:
        return candidates[0], 'protobuf'
    raise ValueError('%d valid decoding candidates' % len(candidates))


def extract_players(root, capture, time_s):
    for field, wire, content in root:
        if field != 5 or wire != 2:  # repeated world objects
            continue
        try:
            obj = protobuf_fields(content)
            if value(obj, 3, 0) != 1:  # observed player-base object type
                continue
            loc = protobuf_fields(value(obj, 2, 2))
            server, x, y = (value(loc, n, 0) for n in (1, 2, 3))
            details = protobuf_fields(value(obj, 4, 2))
            username = value(details, 4, 2)
            pid = value(details, 1, 0)
            level = value(details, 2, 0)
            if username is None or None in (pid, server, x, y, level):
                continue
            username = username.decode('utf-8')
            if not username or not username.isprintable() or len(username) > 64:
                continue
            tag = value(details, 6, 2, b'').decode('utf-8')
            alliance_name = value(details, 7, 2, b'').decode('utf-8')
            if not (0 <= x <= 5000 and 0 <= y <= 5000 and 0 <= level <= 200):
                continue
            yield dict(server=server, x=x, y=y, username=username,
                       alliance_tag=tag, alliance_name=alliance_name,
                       base_level=level, player_id=pid,
                       capture=capture, time_s=round(time_s, 4) if time_s is not None else '')
        except (UnicodeDecodeError, TypeError, ValueError):
            continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('captures', nargs='+', type=Path)
    parser.add_argument('--output', '-o', type=Path, default=Path('zroute_decoded_players.csv'))
    args = parser.parse_args()
    best = {}
    counts = Counter()
    for sequence, file in enumerate(args.captures):
        if not file.is_file():
            parser.error('Missing file: %s' % file)
        local_counts = Counter()
        for name, when, raw in application_messages(file):
            local_counts['map_messages'] += 1
            try:
                decoded, format_name = decode_payload(raw)
                root = map_root(decoded)
                local_counts['decoded_' + format_name] += 1
            except ValueError:
                local_counts['undecoded'] += 1
                continue
            for row in extract_players(root, file.name, when):
                local_counts['base_observations'] += 1
                # Later file arguments and later message times take precedence.
                key = (row['server'], row['player_id'])
                if key not in best or (sequence, when or 0) > best[key][0]:
                    best[key] = ((sequence, when or 0), row)
        counts.update(local_counts)
        print('%s: %d map messages, %d decoded (%d gzip, %d plain), %d base observations' % (
            file.name, local_counts['map_messages'],
            local_counts['decoded_gzip'] + local_counts['decoded_protobuf'],
            local_counts['decoded_gzip'], local_counts['decoded_protobuf'],
            local_counts['base_observations']))
    output = sorted([v[1] for v in best.values()], key=lambda r: (r['server'], r['alliance_tag'], r['username'].casefold()))
    fieldnames = ['server', 'x', 'y', 'username', 'alliance_tag', 'alliance_name',
                  'base_level', 'player_id', 'capture', 'time_s']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='', encoding='utf-8-sig') as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output)
    print('\n%d unique player bases from %d observations. Saved: %s' % (
        len(output), counts['base_observations'], args.output))
    if counts['undecoded']:
        print('Note: %d map responses were not decoded.' % counts['undecoded'])


if __name__ == '__main__':
    main()