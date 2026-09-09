"""Tests for EAPOL detection in raw 802.11 frames (beacon_parser.eapol_bssid).
Run: python3 beacon_parser_test.py
"""
import struct
import sys

from beacon_parser import eapol_bssid, EAPOL_ETHERTYPE

fails = 0


def check(cond, msg):
    global fails
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        fails += 1


RADIOTAP = bytes([0x00, 0x00, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00])  # v0, len 8, no fields
AP = bytes([0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF])
STA = bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66])
AP_STR = "AA:BB:CC:DD:EE:FF"


def frame(subtype, fc1, a1, a2, a3, ethertype, qos=False, htc=False,
          snap=b'\xaa\xaa\x03\x00\x00\x00', with_radiotap=True):
    fc0 = (subtype << 4) | (2 << 2)  # type 2 = data
    body = bytes([fc0, fc1]) + b'\x00\x00' + a1 + a2 + a3 + b'\x00\x00'  # +duration +seq
    if qos:
        body += b'\x00\x00'          # QoS control
        if htc:
            body += b'\x00\x00\x00\x00'  # HT control
    body += snap + struct.pack('>H', ethertype) + b'\x01\x03\x00\x5f'   # + a little EAPOL body
    return (RADIOTAP if with_radiotap else b'') + body


def main():
    # QoS data, FromDS (AP -> station): BSSID is addr2.
    f = frame(8, 0x02, STA, AP, STA, EAPOL_ETHERTYPE, qos=True)
    check(eapol_bssid(f) == AP_STR, "QoS data FromDS -> addr2 is the BSSID")

    # Non-QoS data, ToDS (station -> AP): BSSID is addr1.
    f = frame(0, 0x01, AP, STA, STA, EAPOL_ETHERTYPE, qos=False)
    check(eapol_bssid(f) == AP_STR, "data ToDS -> addr1 is the BSSID")

    # QoS data with the +HTC/Order bit: 4 extra header bytes, still found.
    f = frame(8, 0x02 | 0x80, STA, AP, STA, EAPOL_ETHERTYPE, qos=True, htc=True)
    check(eapol_bssid(f) == AP_STR, "QoS+HTC data FromDS -> BSSID at shifted offset")

    # IBSS (neither DS bit): BSSID is addr3.
    f = frame(0, 0x00, STA, STA, AP, EAPOL_ETHERTYPE, qos=False)
    check(eapol_bssid(f) == AP_STR, "no DS bits -> addr3 is the BSSID")

    # A data frame carrying IP, not EAPOL -> not a handshake.
    f = frame(8, 0x02, STA, AP, STA, 0x0800, qos=True)
    check(eapol_bssid(f) is None, "non-EAPOL EtherType (IPv4) is ignored")

    # Right EtherType but wrong LLC/SNAP prefix -> ignored.
    f = frame(8, 0x02, STA, AP, STA, EAPOL_ETHERTYPE, qos=True, snap=b'\x00\x00\x00\x00\x00\x00')
    check(eapol_bssid(f) is None, "EAPOL EtherType without a SNAP header is ignored")

    # A Protected (encrypted) data frame is skipped: the 4-way handshake is
    # never encrypted, and an encrypted payload can't be a readable SNAP header.
    f = frame(8, 0x02 | 0x40, STA, AP, STA, EAPOL_ETHERTYPE, qos=True)
    check(eapol_bssid(f) is None, "Protected (encrypted) data frame is skipped")

    # A management (beacon) frame is not data -> ignored.
    beacon = RADIOTAP + bytes([0x80, 0x00]) + b'\x00\x00' + STA + AP + AP + b'\x00\x00'
    check(eapol_bssid(beacon) is None, "management frame is ignored")

    # A QoS-null data frame carries no payload -> ignored.
    f = frame(12, 0x02, STA, AP, STA, EAPOL_ETHERTYPE, qos=True)
    check(eapol_bssid(f) is None, "QoS-null data subtype is ignored")

    # Truncated before the SNAP header -> no crash, None.
    check(eapol_bssid(RADIOTAP + bytes([0x88, 0x02]) + b'\x00' * 20) is None,
          "truncated data frame returns None safely")

    # Garbage / too short -> None.
    check(eapol_bssid(b'') is None and eapol_bssid(b'\x00\x00') is None,
          "empty/short input returns None safely")

    print("\nTOTAL FAILURES: %d" % fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
