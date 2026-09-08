"""Raw 802.11 beacon frame parser — extracts AP info from pcap stream.
Parses RSN/WPA Information Elements for accurate encryption detection.
No external dependencies — pure Python struct unpacking."""

import struct


# 802.11 frame types
FRAME_TYPE_MGMT = 0
FRAME_SUBTYPE_BEACON = 8
FRAME_SUBTYPE_PROBE_RESP = 5

# Information Element tags
IE_SSID = 0
IE_DS_PARAMETER = 3
IE_RSN = 48
IE_VENDOR = 221

# Microsoft WPA OUI
WPA_OUI = b'\x00\x50\xf2\x01'

# AKM suite OUIs
AKM_PSK = 2
AKM_SAE = 8
AKM_FT_SAE = 9
AKM_PSK_SHA256 = 6

# Cipher suite types
CIPHER_CCMP = 4
CIPHER_TKIP = 2
CIPHER_GCMP = 8
CIPHER_GCMP256 = 9
CIPHER_CCMP256 = 10

CIPHER_NAMES = {
    CIPHER_TKIP: 'TKIP',
    CIPHER_CCMP: 'CCMP128',
    CIPHER_GCMP: 'GCMP128',
    CIPHER_GCMP256: 'GCMP256',
    CIPHER_CCMP256: 'CCMP256',
}

AKM_NAMES = {
    1: 'EAP',
    2: 'PSK',
    3: 'FT-EAP',
    4: 'FT-PSK',
    6: 'PSK-SHA256',
    8: 'SAE',
    9: 'FT-SAE',
    12: 'EAP-SHA256',
    18: 'OWE',
}


def parse_beacon(frame_bytes):
    """Parse a raw 802.11 beacon/probe-resp frame.

    Args:
        frame_bytes: Raw 802.11 frame (after radiotap header)

    Returns:
        dict with bssid, ssid, channel, encryption, auth_mode_string
        or None if not a beacon/probe-resp
    """
    if len(frame_bytes) < 24:
        return None

    # Frame control (2 bytes, little-endian)
    fc = struct.unpack_from('<H', frame_bytes, 0)[0]
    frame_type = (fc >> 2) & 0x03
    frame_subtype = (fc >> 4) & 0x0f

    if frame_type != FRAME_TYPE_MGMT:
        return None
    if frame_subtype not in (FRAME_SUBTYPE_BEACON, FRAME_SUBTYPE_PROBE_RESP):
        return None

    # MAC addresses
    # addr1 = DA (destination), addr2 = SA (source), addr3 = BSSID
    bssid = _format_mac(frame_bytes[16:22])

    # Fixed parameters (12 bytes after MAC header): timestamp(8) + interval(2) + capability(2)
    if len(frame_bytes) < 36:
        return None

    capability = struct.unpack_from('<H', frame_bytes, 34)[0]
    has_privacy = bool(capability & 0x0010)

    # Parse Information Elements (starting at offset 36)
    ies = _parse_ies(frame_bytes[36:])

    # SSID
    ssid = ''
    if IE_SSID in ies:
        try:
            ssid = ies[IE_SSID].decode('utf-8', errors='replace')
        except Exception:
            ssid = ''

    # Channel from DS Parameter Set
    channel = 0
    if IE_DS_PARAMETER in ies and len(ies[IE_DS_PARAMETER]) >= 1:
        channel = ies[IE_DS_PARAMETER][0]

    # Encryption detection
    rsn_info = None
    wpa_info = None

    if IE_RSN in ies:
        rsn_info = _parse_rsn_ie(ies[IE_RSN])

    # Check vendor IEs for WPA1
    for vendor_data in ies.get('vendors', []):
        if vendor_data[:4] == WPA_OUI:
            wpa_info = _parse_wpa_ie(vendor_data[4:])

    # Build encryption string matching pager format
    encryption, auth_string = _build_auth_string(has_privacy, rsn_info, wpa_info)

    return {
        'bssid': bssid,
        'ssid': ssid,
        'channel': channel,
        'encryption': encryption,
        'auth_mode': auth_string,
    }


def parse_radiotap_and_beacon(packet):
    """Parse a packet with radiotap header + 802.11 frame.

    Returns:
        (signal_dbm, frequency, beacon_dict) or (None, None, None)
    """
    if len(packet) < 8:
        return None, None, None

    # Radiotap header
    rt_version = packet[0]
    if rt_version != 0:
        return None, None, None

    rt_len = struct.unpack_from('<H', packet, 2)[0]
    if rt_len > len(packet):
        return None, None, None

    # Extract signal and frequency from radiotap
    signal = -80
    frequency = 0

    if rt_len >= 8:
        present = struct.unpack_from('<I', packet, 4)[0]

        # Skip past all present flag words (handle extended present flags)
        offset = 8
        p = present
        while p & (1 << 31):
            if offset + 4 > rt_len:
                break
            p = struct.unpack_from('<I', packet, offset)[0]
            offset += 4

        # Now parse fields based on the FIRST present word
        # Bit 0: TSFT (8 bytes, aligned to 8)
        if present & (1 << 0):
            offset = (offset + 7) & ~7
            offset += 8
        # Bit 1: Flags (1 byte)
        if present & (1 << 1):
            offset += 1
        # Bit 2: Rate (1 byte)
        if present & (1 << 2):
            offset += 1
        # Bit 3: Channel (4 bytes: 2 freq + 2 flags, aligned to 2)
        if present & (1 << 3):
            offset = (offset + 1) & ~1
            if offset + 4 <= rt_len:
                frequency = struct.unpack_from('<H', packet, offset)[0]
            offset += 4
        # Bit 4: FHSS (2 bytes)
        if present & (1 << 4):
            offset += 2
        # Bit 5: dBm Antenna Signal (1 byte, signed)
        if present & (1 << 5):
            if offset < rt_len:
                signal = struct.unpack_from('b', packet, offset)[0]
            offset += 1

    # Parse the 802.11 frame after radiotap
    beacon = parse_beacon(packet[rt_len:])
    return signal, frequency, beacon


def _format_mac(mac_bytes):
    """Format 6 bytes as MAC address string."""
    return ':'.join(f'{b:02X}' for b in mac_bytes)


def _parse_ies(data):
    """Parse Information Elements from beacon body."""
    ies = {}
    vendors = []
    offset = 0

    while offset + 2 <= len(data):
        tag = data[offset]
        length = data[offset + 1]
        offset += 2

        if offset + length > len(data):
            break

        value = data[offset:offset + length]

        if tag == IE_VENDOR:
            vendors.append(value)
        elif tag not in ies:
            ies[tag] = value

        offset += length

    ies['vendors'] = vendors
    return ies


def _parse_rsn_ie(data):
    """Parse RSN Information Element (WPA2/WPA3)."""
    if len(data) < 2:
        return None

    info = {'version': 1, 'group_cipher': None, 'pairwise': [], 'akm': []}

    offset = 0
    info['version'] = struct.unpack_from('<H', data, offset)[0]
    offset += 2

    # Group cipher suite (4 bytes)
    if offset + 4 <= len(data):
        info['group_cipher'] = data[offset + 3]
        offset += 4

    # Pairwise cipher suites
    if offset + 2 <= len(data):
        count = struct.unpack_from('<H', data, offset)[0]
        offset += 2
        for _ in range(count):
            if offset + 4 <= len(data):
                info['pairwise'].append(data[offset + 3])
                offset += 4

    # AKM suites
    if offset + 2 <= len(data):
        count = struct.unpack_from('<H', data, offset)[0]
        offset += 2
        for _ in range(count):
            if offset + 4 <= len(data):
                info['akm'].append(data[offset + 3])
                offset += 4

    return info


def _parse_wpa_ie(data):
    """Parse WPA1 vendor IE (after OUI+type prefix)."""
    if len(data) < 2:
        return None

    info = {'version': 1, 'group_cipher': None, 'pairwise': [], 'akm': []}

    offset = 0
    info['version'] = struct.unpack_from('<H', data, offset)[0]
    offset += 2

    if offset + 4 <= len(data):
        info['group_cipher'] = data[offset + 3]
        offset += 4

    if offset + 2 <= len(data):
        count = struct.unpack_from('<H', data, offset)[0]
        offset += 2
        for _ in range(count):
            if offset + 4 <= len(data):
                info['pairwise'].append(data[offset + 3])
                offset += 4

    if offset + 2 <= len(data):
        count = struct.unpack_from('<H', data, offset)[0]
        offset += 2
        for _ in range(count):
            if offset + 4 <= len(data):
                info['akm'].append(data[offset + 3])
                offset += 4

    return info


def _build_auth_string(has_privacy, rsn_info, wpa_info):
    """Build encryption type and Wigle-compatible auth mode string.

    Returns:
        (encryption_type, auth_string)
        e.g., ('WPA3', '[WPA3-PSK+SAE-CCMP128 WPA2-PSK+SAE-CCMP128]')
    """
    parts = []
    encryption = 'Open'

    if rsn_info:
        akm_names = []
        for a in rsn_info.get('akm', []):
            name = AKM_NAMES.get(a, f'UNK{a}')
            akm_names.append(name)

        cipher_name = CIPHER_NAMES.get(
            rsn_info['pairwise'][0] if rsn_info['pairwise'] else CIPHER_CCMP,
            'CCMP128'
        )

        has_sae = any(a in (AKM_SAE, AKM_FT_SAE) for a in rsn_info.get('akm', []))
        has_psk = any(a in (AKM_PSK, AKM_PSK_SHA256, 4) for a in rsn_info.get('akm', []))

        if has_sae and has_psk:
            akm_str = 'PSK+SAE'
            parts.append(f'WPA3-{akm_str}-{cipher_name}')
            parts.append(f'WPA2-{akm_str}-{cipher_name}')
            encryption = 'WPA3'
        elif has_sae:
            akm_str = 'SAE'
            parts.append(f'WPA3-{akm_str}-{cipher_name}')
            encryption = 'WPA3'
        else:
            akm_str = '+'.join(akm_names) if akm_names else 'PSK'
            parts.append(f'WPA2-{akm_str}-{cipher_name}')
            encryption = 'WPA2'

    if wpa_info:
        cipher_name = CIPHER_NAMES.get(
            wpa_info['pairwise'][0] if wpa_info['pairwise'] else CIPHER_TKIP,
            'TKIP'
        )
        akm_names = []
        for a in wpa_info.get('akm', []):
            name = AKM_NAMES.get(a, f'UNK{a}')
            akm_names.append(name)
        akm_str = '+'.join(akm_names) if akm_names else 'PSK'
        parts.append(f'WPA1-{akm_str}-{cipher_name}')
        if encryption == 'Open':
            encryption = 'WPA'

    if parts:
        auth_string = '[' + ' '.join(parts) + ']'
    elif has_privacy:
        auth_string = '[WEP]'
        encryption = 'WEP'
    else:
        auth_string = '[ESS]'
        encryption = 'Open'

    return encryption, auth_string
