import sys
import os
import struct

def find_imei_offsets(devinfo):
    imei_offsets = []
    for offset in range(0, len(devinfo) - 15):
        # Check if the 15 characters are digits and the next byte is NULL (\x00)
        if devinfo[offset:offset + 15].isdigit() and devinfo[offset + 15] == 0:
            imei_offsets.append(offset)
            if len(imei_offsets) == 2:  # Only need 2 IMEI offsets
                break
    return imei_offsets

def main():
    # Check command-line arguments
    if len(sys.argv) < 2:
        print("Usage: %s <devinfo file>" % sys.argv[0])
        sys.exit(1)

    devinfo_file = sys.argv[1]

    if not os.path.isfile(devinfo_file):
        print("Error: %s does not exist" % devinfo_file)
        sys.exit(1)

    # Read the devinfo file
    with open(devinfo_file, "rb") as f:
        devinfo = f.read()

        # Check if magic matches "DEVI"
        if devinfo[0:4] != b"DEVI":
            print("Error: %s is not a valid devinfo file" % devinfo_file)
            sys.exit(1)

        # Find IMEI offsets
        imei_offsets = find_imei_offsets(devinfo)
        if len(imei_offsets) < 2:
            print("Error: Could not find both IMEI offsets!")
            sys.exit(1)

        # Print IMEI offsets
        print("imei1: 0x%X" % imei_offsets[0])
        print("imei2: 0x%X" % imei_offsets[1])

if __name__ == "__main__":
    main()
