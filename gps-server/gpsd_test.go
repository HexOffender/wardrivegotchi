package main

import (
	"bufio"
	"bytes"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"
)

// fakeGPSD stands in for gpsd on the real port: it greets clients with a
// VERSION line and answers ?DEVICES; with the device list it was given.
func fakeGPSD(t *testing.T, devicePath string) {
	t.Helper()

	ln, err := net.Listen("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(gpsdPort)))
	if err != nil {
		t.Skipf("could not bind port %d: %v", gpsdPort, err)
	}
	t.Cleanup(func() { ln.Close() })

	go func() {
		for {
			conn, err := ln.Accept()
			if err != nil {
				return
			}

			go func(conn net.Conn) {
				defer conn.Close()

				conn.Write([]byte(`{"class":"VERSION","release":"3.25","rev":"3.25"}` + "\n"))

				scanner := bufio.NewScanner(conn)
				for scanner.Scan() {
					if strings.Contains(scanner.Text(), "?DEVICES;") {
						conn.Write([]byte(`{"class":"DEVICES","devices":[{"class":"DEVICE","path":"` +
							devicePath + `","driver":"NMEA0183"}]}` + "\n"))
						return
					}
				}
			}(conn)
		}
	}()
}

func TestVerifyGPSDAcceptsOurDevice(t *testing.T) {
	fakeGPSD(t, "/dev/pts/3")

	if err := verifyGPSD("/dev/pts/3", make(chan struct{})); err != nil {
		t.Errorf("verifyGPSD rejected the device it is serving: %v", err)
	}
}

// The failure this exists to catch: a gpsd respawned by the Pager answers on
// the port perfectly well while watching the real serial GPS, so it never
// reports a fix and nothing else in the payload notices.
func TestVerifyGPSDRejectsAnotherDevice(t *testing.T) {
	fakeGPSD(t, "/dev/ttyS1")

	err := verifyGPSD("/dev/pts/3", make(chan struct{}))
	if err == nil {
		t.Fatal("verifyGPSD accepted a gpsd serving a different device")
	}
	if !strings.Contains(err.Error(), "another device") {
		t.Errorf("error should say the device is wrong, got: %v", err)
	}
	if !strings.Contains(err.Error(), "/dev/ttyS1") {
		t.Errorf("error should name the device gpsd is actually serving, got: %v", err)
	}
}

func TestVerifyGPSDReportsExit(t *testing.T) {
	exited := make(chan struct{})
	close(exited)

	err := verifyGPSD("/dev/pts/3", exited)
	if err == nil || !strings.Contains(err.Error(), "not running") {
		t.Errorf("expected a not-running error, got: %v", err)
	}
}

func TestPortInUse(t *testing.T) {
	if portInUse(gpsdPort) {
		t.Skipf("port %d is already in use", gpsdPort)
	}

	fakeGPSD(t, "/dev/pts/3")

	if !portInUse(gpsdPort) {
		t.Error("portInUse did not see the listener")
	}
}

// NMEA carries UTC. time.UnixMilli returns local time, so a Pager set to a
// non-UTC timezone used to put its offset into every sentence.
func TestGPRMCUsesUTC(t *testing.T) {
	eastern := time.FixedZone("EDT", -4*60*60)
	ts := time.Date(2026, 9, 5, 21, 22, 46, 0, eastern) // 01:22:46 UTC on the 6th

	var buf bytes.Buffer
	buildGPRMC(&buf, 45.420820, -75.700106, ts, "A", "A")
	sentence := buf.String()

	fields := strings.Split(strings.TrimSuffix(sentence, "\r\n"), ",")
	if len(fields) < 10 {
		t.Fatalf("unexpected sentence: %q", sentence)
	}

	if fields[1] != "012246.00" {
		t.Errorf("time should be UTC (012246.00), got %q in %q", fields[1], sentence)
	}
	if fields[9] != "060926" {
		t.Errorf("date should be UTC (060926), got %q in %q", fields[9], sentence)
	}
	if fields[3] != "4525.249200" || fields[4] != "N" {
		t.Errorf("latitude: got %q,%q", fields[3], fields[4])
	}
	if fields[5] != "07542.006360" || fields[6] != "W" {
		t.Errorf("longitude: got %q,%q", fields[5], fields[6])
	}
}

// The checksum is what gpsd uses to reject a malformed sentence, so verify it
// independently of the code that writes it.
func TestGPRMCChecksum(t *testing.T) {
	var buf bytes.Buffer
	buildGPRMC(&buf, 45.420820, -75.700106, time.Now(), "A", "A")
	sentence := strings.TrimSuffix(buf.String(), "\r\n")

	star := strings.LastIndex(sentence, "*")
	if star < 0 || !strings.HasPrefix(sentence, "$") {
		t.Fatalf("malformed sentence: %q", sentence)
	}

	var want byte
	for i := 1; i < star; i++ {
		want ^= sentence[i]
	}

	got, err := strconv.ParseUint(sentence[star+1:], 16, 8)
	if err != nil {
		t.Fatalf("unparseable checksum in %q: %v", sentence, err)
	}
	if byte(got) != want {
		t.Errorf("checksum %02X does not match computed %02X for %q", got, want, sentence)
	}
}

// The supervisor exists for one scenario: the Pager restores its own
// device-less gpsd, which takes the port and answers clients while never
// reporting a fix. Checking only at startup misses it.
func TestSupervisorNoticesEviction(t *testing.T) {
	fakeGPSD(t, "/dev/ttyS1")

	m := newGPSDManager("/dev/pts/3")
	m.exited = make(chan struct{})

	reason := m.unhealthy()
	if reason == "" {
		t.Fatal("supervisor did not notice another gpsd holding the port")
	}
	if !strings.Contains(reason, "taken port") || !strings.Contains(reason, "/dev/ttyS1") {
		t.Errorf("reason should name the intruder, got: %s", reason)
	}
}

func TestSupervisorLeavesOurGPSDAlone(t *testing.T) {
	fakeGPSD(t, "/dev/pts/3")

	m := newGPSDManager("/dev/pts/3")
	m.exited = make(chan struct{})

	if reason := m.unhealthy(); reason != "" {
		t.Errorf("supervisor wanted to restart a healthy gpsd: %s", reason)
	}
}

func TestSupervisorNoticesExit(t *testing.T) {
	exited := make(chan struct{})
	close(exited)

	m := newGPSDManager("/dev/pts/3")
	m.exited = exited

	if reason := m.unhealthy(); !strings.Contains(reason, "no longer running") {
		t.Errorf("expected an exit reason, got: %q", reason)
	}
}
