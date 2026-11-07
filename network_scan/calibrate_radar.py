"""Create a radar UI template from a previously saved world-map screenshot.

This is an OFFLINE image crop. It never connects to BlueStacks, clicks,
zooms, or runs a scan. Crop a stable radar edge/icon, not moving terrain.
Coordinates are in the FULL 1080x1920 screenshot.
Example:
    python network_scan/calibrate_radar.py --image path/to/radar_not_verified.png --crop 830 40 866 78
"""
import argparse
from pathlib import Path

import cv2

DEFAULT_ROI=(800,25,1060,270)


def calibrate(image_file, crop, output, roi=DEFAULT_ROI):
    source=Path(image_file)
    if not source.is_file():
        raise FileNotFoundError(f'Screenshot not found: {source}')
    im=cv2.imread(str(source),cv2.IMREAD_COLOR)
    if im is None:
        raise ValueError(f'Could not read image: {source}')
    h,w=im.shape[:2]
    l,t,r,b=(int(v) for v in crop)
    rl,rt,rr,rb=roi
    if not (0<=l<r<=w and 0<=t<b<=h):
        raise ValueError(f'Invalid crop {crop} for {w}x{h} screenshot')
    if not (rl<=l<r<=rr and rt<=t<b<=rb):
        raise ValueError(f'Crop must lie inside the minimap ROI {roi}')
    if r-l<10 or b-t<10:
        raise ValueError('Template must be at least 10x10 pixels')
    region=cv2.cvtColor(im[t:b,l:r],cv2.COLOR_BGR2GRAY)
    if float(region.std())<8:
        raise ValueError('Selected image patch is too uniform; choose a distinctive stable radar feature')
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if not cv2.imwrite(str(output),region):
        raise OSError(f'Failed writing template: {output}')
    print(f'Saved radar template {output} ({r-l}x{b-t})')
    print('IMPORTANT: this only creates a reference image. It does not prove')
    print('that the chosen crop is a stationary radar UI element.')
    print('Verify against a second world map screenshot before scanning.')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image',type=Path,required=True,
                    help='Actual screenshot after successful zoom')
    ap.add_argument('--crop',type=int,nargs=4,required=True,
                    metavar=('LEFT','TOP','RIGHT','BOTTOM'))
    ap.add_argument('--out',type=Path,default=Path('network_scans/radar_icon.png'))
    args=ap.parse_args()
    calibrate(args.image,args.crop,args.out)


if __name__=='__main__':
    main()
