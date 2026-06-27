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

def luhn_check(imei: str) -> bool:
    """Validate IMEI using the Luhn algorithm."""
    digits = [int(d) for d in imei]
    odd = digits[-1::-2]
    even = [sum(divmod(d * 2, 10)) for d in digits[-2::-2]]
    return (sum(odd) + sum(even)) % 10 == 0

def parse_devinfo_records(data: bytes) -> dict:
    """
    Parse a devinfo.img binary blob and return a dict mapping key names to record info.
    Handles TLV structure: DIUS/DIFR signature, total_len, key_len, key, value.
    Correctly skips padding records (key_len > total_len or key_len == 0).
    """
    records = {}
    idx = 128  # Skip 128-byte partition header
    while idx < len(data):
        if idx + 12 > len(data):
            break
        sig = data[idx:idx + 4]
        if sig not in [b'DIUS', b'DIFR']:
            idx += 1
            continue
        total_len = int.from_bytes(data[idx + 4:idx + 8], 'little')
        key_len = int.from_bytes(data[idx + 8:idx + 12], 'little')
        # Bounds check
        if total_len <= 0 or idx + 12 + total_len > len(data):
            idx += 4
            continue
        # Treat as padding if key_len is invalid
        if key_len <= 0 or key_len > total_len:
            idx += 12 + total_len
            continue
        key_bytes = data[idx + 12:idx + 12 + key_len]
        val_len = total_len - key_len
        val_bytes = data[idx + 12 + key_len:idx + 12 + key_len + val_len]
        key = key_bytes.decode('ascii', errors='ignore').rstrip('\x00')
        if key:
            records[key] = {
                'record_offset': idx,
                'value_offset': idx + 12 + key_len,
                'value_bytes': val_bytes,
                'total_len': total_len,
                'key_len': key_len,
            }
        idx += 12 + total_len
    return records

def patch_devinfo_tlv(template_data: bytes, new_imei1: str, new_imei2: str) -> bytes:
    """
    Patches template_data with new IMEIs using parsed TLV record offsets.
    Returns the modified bytearray/bytes or raises ValueError.
    """
    records = parse_devinfo_records(template_data)
    if "imei1" not in records or "imei2" not in records:
        raise ValueError("Could not locate IMEI record keys in the template.")
    
    rec1 = records["imei1"]
    rec2 = records["imei2"]
    
    new_val1 = new_imei1.encode("ascii") + b"\x00"
    new_val2 = new_imei2.encode("ascii") + b"\x00"
    
    if len(new_val1) != len(rec1["value_bytes"]) or len(new_val2) != len(rec2["value_bytes"]):
        raise ValueError("IMEI value size does not match the template record.")
    
    patched = bytearray(template_data)
    patched[rec1["value_offset"]:rec1["value_offset"] + len(new_val1)] = new_val1
    patched[rec2["value_offset"]:rec2["value_offset"] + len(new_val2)] = new_val2
    
    return bytes(patched)

