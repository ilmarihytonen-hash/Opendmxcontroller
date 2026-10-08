import struct
import unittest

from lumendesk.controls import make_osc_message, parse_osc_message
from lumendesk.protocols import (
    make_artnet_packet,
    make_sacn_packet,
    sacn_multicast_address,
)


class DmxProtocolTests(unittest.TestCase):
    def setUp(self):
        self.data = bytes(index % 256 for index in range(512))

    def test_artnet_packet_header_and_universe(self):
        packet = make_artnet_packet(3, self.data, sequence=7)
        self.assertEqual(packet[:8], b"Art-Net\x00")
        self.assertEqual(packet[8:10], struct.pack("<H", 0x5000))
        self.assertEqual(packet[12], 7)
        self.assertEqual(packet[14:16], struct.pack("<H", 2))
        self.assertEqual(packet[18:], self.data)

    def test_artnet_rejects_wrong_frame_size_and_universe(self):
        with self.assertRaises(ValueError):
            make_artnet_packet(0, self.data)
        with self.assertRaises(ValueError):
            make_artnet_packet(1, self.data[:-1])

    def test_sacn_packet_pdu_lengths_and_dmx_data(self):
        packet = make_sacn_packet(1, self.data, sequence=9)
        self.assertEqual(packet[:4], b"\x00\x10\x00\x00")
        self.assertEqual(packet[16:18], struct.pack(">H", 0x7000 | 622))
        self.assertEqual(packet[38:40], struct.pack(">H", 0x7000 | 600))
        self.assertEqual(packet[115:117], struct.pack(">H", 0x7000 | 523))
        self.assertEqual(packet[126:], self.data)
        self.assertEqual(packet[113:115], struct.pack(">H", 1))
        self.assertEqual(packet[111], 9)

    def test_sacn_rejects_invalid_cid(self):
        with self.assertRaises(ValueError):
            make_sacn_packet(1, self.data, cid=b"short")

    def test_sacn_uses_per_universe_multicast_address(self):
        self.assertEqual(sacn_multicast_address(1), "239.255.0.1")
        self.assertEqual(sacn_multicast_address(256), "239.255.1.0")
        self.assertEqual(sacn_multicast_address(63999), "239.255.249.255")

    def test_osc_integer_message_round_trip(self):
        message = make_osc_message("/lumendesk/universe/2/channel/20", 201)
        self.assertEqual(
            parse_osc_message(message),
            ("/lumendesk/universe/2/channel/20", 201),
        )

    def test_osc_float_message_round_trip(self):
        address, value = parse_osc_message(make_osc_message("/test", 0.5))
        self.assertEqual(address, "/test")
        self.assertAlmostEqual(value, 0.5)

    def test_osc_rejects_unsupported_tags(self):
        with self.assertRaises(ValueError):
            parse_osc_message(b"/test\x00\x00\x00,s\x00\x00")


if __name__ == "__main__":
    unittest.main()
