"""Network qualification checks; inactive default kernel tunnels are not egress."""
import unittest
import quality_delivery_review_canary as canary


class DeliveryReviewCanaryNetworkTests(unittest.TestCase):
    header='Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n'
    local6='00000000000000000000000000000001 80 0 00 0 0 0 0 80200001 lo\n'

    def test_only_loopback_up_and_only_loopback_routes_are_isolated(self):
        canary.isolated_network({'lo'},self.header,self.local6)

    def test_non_loopback_up_is_rejected_even_without_a_default_route(self):
        for active in ({'lo','eth0'},{'lo','tunl0'},set()):
            with self.subTest(active=active),self.assertRaises(AssertionError):
                canary.isolated_network(active,self.header,self.local6)

    def test_non_loopback_ipv4_or_ipv6_route_is_rejected_even_if_interface_is_down(self):
        for routes4,routes6 in ((self.header+'eth0 0 0 0 0 0 0 0 0 0 0\n',self.local6),
                (self.header,self.local6.replace(' lo\n',' eth0\n'))):
            with self.subTest(ipv4=routes4),self.assertRaises(AssertionError):
                canary.isolated_network({'lo'},routes4,routes6)


if __name__=='__main__':unittest.main()
