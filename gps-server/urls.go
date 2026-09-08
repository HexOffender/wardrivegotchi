// Where the server can be reached. It listens on every interface, so the
// Management AP is only one of the ways in.
package main

import (
	"fmt"
	"net"
)

// localAddresses returns the usable IP addresses currently assigned to the
// Pager's interfaces. mobile2gps listens on every interface, so the server is
// reachable at any of these - over the Management AP, over the USB-C Ethernet
// interface, or over a tethered connection.
func localAddresses() []net.IP {
	var ips []net.IP

	ifaces, err := net.Interfaces()
	if err != nil {
		warnf("could not enumerate network interfaces: %v", err)
		return ips
	}

	for _, iface := range ifaces {
		if iface.Flags&net.FlagUp == 0 {
			continue
		}

		addrs, err := iface.Addrs()
		if err != nil {
			continue
		}

		for _, addr := range addrs {
			var ip net.IP
			switch v := addr.(type) {
			case *net.IPNet:
				ip = v.IP
			case *net.IPAddr:
				ip = v.IP
			}

			if ip == nil || ip.IsMulticast() {
				continue
			}

			// IPv6 link-local addresses need a zone index to be usable in a
			// URL, so they are not worth advertising or certifying.
			if ip.To4() == nil && ip.IsLinkLocalUnicast() {
				continue
			}

			ips = appendUniqueIP(ips, ip)
		}
	}

	return ips
}

// appendUniqueIP appends ip to ips unless it is already present.
func appendUniqueIP(ips []net.IP, ip net.IP) []net.IP {
	for _, existing := range ips {
		if existing.Equal(ip) {
			return ips
		}
	}
	return append(ips, ip)
}

// reachableURLs returns every address the server can be opened at. The
// Management AP is only one of them - the same page is served over the USB-C
// Ethernet interface and over any tethered connection.
func reachableURLs() []string {
	var urls []string

	for _, ip := range localAddresses() {
		if ip.IsLoopback() {
			continue
		}

		host := ip.String()
		if ip.To4() == nil {
			host = "[" + host + "]"
		}
		urls = append(urls, fmt.Sprintf("https://%s:%d", host, httpsPort))
	}

	return urls
}

// logReachableURLs logs the addresses the server can be opened at.
func logReachableURLs() {
	urls := reachableURLs()

	if len(urls) == 0 {
		warnf("no network addresses found - connect the Management AP or a cable first")
		return
	}

	infof("Open one of these on your mobile device:")
	for _, url := range urls {
		infof("   %s", url)
	}
}
