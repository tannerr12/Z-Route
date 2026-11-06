"""Offline tests for recursive raw world-object inspection.

Run: python -m unittest discover -s network_scan -p test_raw_object_inspect.py
No ADB, packet capture, or server access.
"""
import unittest
from raw_object_inspect import numeric_matches, parse_tree


def varint(n):
    parts=[]
    while n>=128:
        parts.append((n&127)|128);n>>=7
    parts.append(n)
    return bytes(parts)


def scalar(n,v):
    return varint(n*8)+varint(v)


def packed(n,data):
    return varint(n*8+2)+varint(len(data))+data


class RawWorldObjectTests(unittest.TestCase):
    def test_deeply_nested_numeric_level_is_discoverable(self):
        # Current flat candidate extraction sees no 120, but the full raw
        # object can contain an undocumented nested field with value 120.
        nested=scalar(7,120)+scalar(8,1700000000)
        root=scalar(1,123456)+packed(2,packed(9,nested))
        tree=parse_tree(root,max_depth=4)
        self.assertEqual(numeric_matches(tree,120),['2.9.7'])
        self.assertEqual(numeric_matches(tree,130),[])

    def test_unknown_opaque_bytes_are_preserved_without_guessing(self):
        obj=packed(37,b'\xff\xfe\xfd')+scalar(99,100)
        tree=parse_tree(obj)
        self.assertEqual(tree[0]['field'],37)
        self.assertEqual(tree[0]['hex_prefix'],'fffefd')
        self.assertEqual(numeric_matches(tree,100),['99'])
        self.assertFalse(tree[0].get('children'))

    def test_fixed_fields_not_mislabeled_as_levels(self):
        # Fixed32/fixed64 represent a raw integer here; no schema claim.
        raw=varint(3*8+5)+(120).to_bytes(4,'little')
        tree=parse_tree(raw)
        self.assertEqual(tree[0]['encoding'],'fixed32')
        self.assertEqual(numeric_matches(tree,120),['3'])

    def test_depth_limit_does_not_blow_up(self):
        deep=scalar(1,120)
        for i in range(8):
            deep=packed(2,deep)
        tree=parse_tree(deep,max_depth=2)
        self.assertEqual(numeric_matches(tree,120),[])
        self.assertIn('children',tree[0])


if __name__=='__main__':
    unittest.main()
