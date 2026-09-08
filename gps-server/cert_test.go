package main

import (
	"crypto/tls"
	"crypto/x509"
	"net"
	"os"
	"testing"
)

func leafOf(t *testing.T, cert tls.Certificate) *x509.Certificate {
	t.Helper()
	leaf, err := x509.ParseCertificate(cert.Certificate[0])
	if err != nil {
		t.Fatal(err)
	}
	return leaf
}

func TestCertLifecycle(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}

	// 1. First run generates a certificate covering every live address plus
	//    the Management AP and loopback.
	first, err := loadOrGenerateCert()
	if err != nil {
		t.Fatal(err)
	}
	firstLeaf := leafOf(t, first)

	for _, want := range certAddresses() {
		if len(missingAddresses(firstLeaf, []net.IP{want})) != 0 {
			t.Errorf("generated cert is missing %s", want)
		}
	}
	t.Logf("generated SAN IPs: %v", firstLeaf.IPAddresses)
	t.Logf("generated SAN DNS: %v", firstLeaf.DNSNames)

	// 2. Second run reuses it - the phone should not be asked to trust a new
	//    certificate when nothing changed.
	second, err := loadOrGenerateCert()
	if err != nil {
		t.Fatal(err)
	}
	if leafOf(t, second).SerialNumber.Cmp(firstLeaf.SerialNumber) != 0 {
		t.Error("certificate was regenerated when addresses had not changed")
	}

	// 3. A certificate that predates a new interface is replaced, and the
	//    replacement keeps the addresses the old one already carried.
	stale := net.ParseIP("10.99.99.99")
	if _, err := generateCert([]net.IP{stale}, []string{"localhost"}); err != nil {
		t.Fatal(err)
	}

	third, err := loadOrGenerateCert()
	if err != nil {
		t.Fatal(err)
	}
	thirdLeaf := leafOf(t, third)

	if missing := missingAddresses(thirdLeaf, []net.IP{stale}); len(missing) != 0 {
		t.Error("replacement cert dropped the previous address")
	}
	if missing := missingAddresses(thirdLeaf, certAddresses()); len(missing) != 0 {
		t.Errorf("replacement cert is missing current addresses: %v", missing)
	}
	t.Logf("replacement SAN IPs: %v", thirdLeaf.IPAddresses)
}

func TestServerNameMatching(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chdir(dir); err != nil {
		t.Fatal(err)
	}

	cert, err := loadOrGenerateCert()
	if err != nil {
		t.Fatal(err)
	}
	leaf := leafOf(t, cert)

	pool := x509.NewCertPool()
	pool.AddCert(leaf)

	// Every advertised address must verify as a server name, which is what
	// stops the browser adding a hostname mismatch on top of the self-signed
	// warning.
	for _, ip := range certAddresses() {
		if err := leaf.VerifyHostname(ip.String()); err != nil {
			t.Errorf("VerifyHostname(%s): %v", ip, err)
		}
	}
	for _, name := range certDNSNames() {
		if err := leaf.VerifyHostname(name); err != nil {
			t.Errorf("VerifyHostname(%s): %v", name, err)
		}
	}
}
