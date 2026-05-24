import os
import re

def find_imei_offsets(devinfo_data):
    """
    Finds the offsets of the two 15-digit IMEIs in the devinfo partition data.
    Ported from di.py.
    """
    if devinfo_data[0:4] != b"DEVI":
        raise ValueError("Invalid devinfo file magic (expected 'DEVI')")
    
    imei_offsets = []
    # Search for 15 digits followed by a NULL byte
    for offset in range(0, len(devinfo_data) - 15):
        if devinfo_data[offset:offset + 15].isdigit() and devinfo_data[offset + 15] == 0:
            imei_offsets.append(offset)
            if len(imei_offsets) == 2:
                break
    
    if len(imei_offsets) < 2:
        raise ValueError(f"Could not find both IMEI offsets! Found: {len(imei_offsets)}")
    
    return imei_offsets[0], imei_offsets[1]

def patch_devinfo(input_path, output_path, imei1, imei2):
    """
    Reads devinfo from input_path, patches it with new IMEIs, and saves to output_path.
    """
    with open(input_path, 'rb') as f:
        data = bytearray(f.read())
    
    off1, off2 = find_imei_offsets(data)
    
    # Update IMEI1
    imei1_bytes = imei1.encode('ascii') + b'\x00'
    data[off1 : off1 + len(imei1_bytes)] = imei1_bytes
    
    # Update IMEI2
    imei2_bytes = imei2.encode('ascii') + b'\x00'
    data[off2 : off2 + len(imei2_bytes)] = imei2_bytes
    
    with open(output_path, 'wb') as f:
        f.write(data)
    
    return True

def prepare_imei_parts(imei):
    """
    Formats IMEI for AT commands (splits into 2-character parts).
    Ported from giant-CPID.py.
    """
    # Slice the 15-digit IMEI into 7 full pairs + 1 single trailing digit
    parts = [imei[i:i + 2] for i in range(0, 14, 2)]   # indices 0-13  → 7 parts
    parts.append(imei[14].ljust(2, '0'))                 # index  14     → 1 part, zero-padded
    parts.append('00')                                   # sentinel / terminator
    return parts

def get_imei_at_commands(imei1, imei2):
    """
    Generates the sequence of AT commands to set IMEIs via umts_router.
    """
    commands = []
    
    # IMEI 1
    parts1 = prepare_imei_parts(imei1)
    for i, part in enumerate(parts1):
        commands.append(f'echo \'AT+GOOGSETNV="CAL.Common.Imei",{i},"{part}"\r\' > /dev/umts_router')
    
    # IMEI 2
    parts2 = prepare_imei_parts(imei2)
    for i, part in enumerate(parts2):
        commands.append(f'echo \'AT+GOOGSETNV="CAL.Common.Imei_2nd",{i},"{part}"\r\' > /dev/umts_router')
        
    return commands
