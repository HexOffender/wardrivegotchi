// TLS certificate handling: a self-signed certificate covering every address
// the Pager currently answers on, so the phone sees one warning rather than two.
package main

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"fmt"
	"math/big"
	"net"
	"os"
	"time"
)

// appendUniqueName appends name to names unless it is already present.
func appendUniqueName(names []string, name string) []string {
	if name == "" {
		return names
	}
	for _, existing := range names {
		if existing == name {
			return names
		}
	}
	return append(names, name)
}

// certAddresses returns the addresses the certificate should cover: every live
// interface address, plus the Management AP and loopback addresses so a
// certificate generated while an interface is down still works later.
func certAddresses() []net.IP {
	ips := localAddresses()
	for _, fallback := range []string{managementIP, "127.0.0.1"} {
		if ip := net.ParseIP(fallback); ip != nil {
			ips = appendUniqueIP(ips, ip)
		}
	}
	return ips
}

// certDNSNames returns the names the certificate should cover. The .local name
// matches the Pager's mDNS hostname where one is advertised.
func certDNSNames() []string {
	names := []string{"localhost", "mobile2gps", "mobile2gps.local"}
	if hostname, err := os.Hostname(); err == nil {
		names = appendUniqueName(names, hostname)
		names = appendUniqueName(names, hostname+".local")
	}
	return names
}

// missingAddresses returns the addresses in ips that cert does not cover.
func missingAddresses(cert *x509.Certificate, ips []net.IP) []net.IP {
	var missing []net.IP

	for _, ip := range ips {
		found := false
		for _, certIP := range cert.IPAddresses {
			if certIP.Equal(ip) {
				found = true
				break
			}
		}
		if !found {
			missing = append(missing, ip)
		}
	}

	return missing
}

// loadOrGenerateCert reuses the saved certificate when it still covers every
// current address, and generates a replacement otherwise. A replacement keeps
// the addresses the old certificate already carried, so the certificate settles
// once it has seen every transport and the phone stops being asked to trust a
// new one.
func loadOrGenerateCert() (tls.Certificate, error) {
	ips := certAddresses()
	names := certDNSNames()

	if _, statErr := os.Stat(certFile); statErr == nil {
		if _, statErr := os.Stat(keyFile); statErr == nil {
			cert, err := tls.LoadX509KeyPair(certFile, keyFile)
			switch {
			case err != nil:
				warnf("could not load the saved certificate, generating a new one: %v", err)
			case len(cert.Certificate) == 0:
				warnf("the saved certificate is empty, generating a new one")
			default:
				leaf, err := x509.ParseCertificate(cert.Certificate[0])
				switch {
				case err != nil:
					warnf("could not parse the saved certificate, generating a new one: %v", err)
				case time.Now().After(leaf.NotAfter):
					infof("the saved certificate has expired, generating a new one")
				default:
					missing := missingAddresses(leaf, ips)
					if len(missing) == 0 {
						infof("Loading existing certificate")
						return cert, nil
					}

					infof("the saved certificate is missing current address(es), generating a new one:")
					for _, ip := range missing {
						infof("   %s", ip)
					}

					// Carry the old addresses and names forward.
					for _, ip := range leaf.IPAddresses {
						ips = appendUniqueIP(ips, ip)
					}
					for _, name := range leaf.DNSNames {
						names = appendUniqueName(names, name)
					}
				}
			}
		}
	}

	return generateCert(ips, names)
}

// generateCert creates a self-signed certificate covering ips and names, and
// saves it alongside its key.
func generateCert(ips []net.IP, names []string) (tls.Certificate, error) {
	infof("Generating self-signed certificate")

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return tls.Certificate{}, err
	}

	// Get hostname for certificate subject
	hostname, err := os.Hostname()
	if err != nil || hostname == "" {
		hostname = "mobile2gps"
	}

	serialNumber, err := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	if err != nil {
		return tls.Certificate{}, fmt.Errorf("failed to generate serial number: %w", err)
	}

	for _, ip := range ips {
		debugf("  covering %s", ip)
	}

	template := x509.Certificate{
		SerialNumber: serialNumber,
		Subject:      pkix.Name{CommonName: hostname},
		NotBefore:    time.Now(),
		NotAfter:     time.Now().AddDate(10, 0, 0), // 10 years
		KeyUsage:     x509.KeyUsageKeyEncipherment | x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
		DNSNames:     names,
		IPAddresses:  ips,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, &template, &template, &key.PublicKey, key)
	if err != nil {
		return tls.Certificate{}, err
	}

	// Save certificate
	certOut, err := os.Create(certFile)
	if err != nil {
		return tls.Certificate{}, err
	}
	if err := pem.Encode(certOut, &pem.Block{Type: "CERTIFICATE", Bytes: certDER}); err != nil {
		certOut.Close()
		return tls.Certificate{}, fmt.Errorf("failed to encode certificate: %w", err)
	}
	if err := certOut.Close(); err != nil {
		return tls.Certificate{}, fmt.Errorf("failed to close certificate file: %w", err)
	}

	// Save private key
	keyDER, err := x509.MarshalECPrivateKey(key)
	if err != nil {
		return tls.Certificate{}, err
	}
	keyOut, err := os.Create(keyFile)
	if err != nil {
		return tls.Certificate{}, err
	}
	if err := pem.Encode(keyOut, &pem.Block{Type: "EC PRIVATE KEY", Bytes: keyDER}); err != nil {
		keyOut.Close()
		return tls.Certificate{}, fmt.Errorf("failed to encode private key: %w", err)
	}
	if err := keyOut.Close(); err != nil {
		return tls.Certificate{}, fmt.Errorf("failed to close key file: %w", err)
	}

	infof("Saved certificate to %s and %s", certFile, keyFile)

	return tls.Certificate{
		Certificate: [][]byte{certDER},
		PrivateKey:  key,
	}, nil
}
