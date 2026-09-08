// gpsd lifecycle: start it on our fake GPS device, and keep it there.
package main

import (
	"bufio"
	"fmt"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

const (
	gpsdBinary = "/usr/sbin/gpsd"
	// How often to confirm gpsd is still serving our device. The Pager brings
	// its own gpsd back whenever its services restart, so this needs to be
	// often enough that a drive does not silently lose its position.
	superviseInterval = 20 * time.Second
)

// gpsdManager owns the gpsd process that reads our fake GPS device.
type gpsdManager struct {
	slaveName string

	mu     sync.Mutex
	cmd    *exec.Cmd
	exited chan struct{}

	shutdown chan struct{}
	once     sync.Once
}

func newGPSDManager(slaveName string) *gpsdManager {
	return &gpsdManager{
		slaveName: slaveName,
		shutdown:  make(chan struct{}),
	}
}

// start frees the port and runs gpsd against our device, then confirms it took.
func (m *gpsdManager) start() error {
	stopExistingGPSD()

	// Full path, for restricted PATH environments like DuckyScript payloads.
	cmd := exec.Command(gpsdBinary, "-N", "-G",
		"-S", strconv.Itoa(gpsdPort),
		m.slaveName)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return fmt.Errorf("could not start gpsd: %w", err)
	}

	exited := make(chan struct{})

	m.mu.Lock()
	m.cmd = cmd
	m.exited = exited
	m.mu.Unlock()

	// gpsd dying after a successful start is the quiet failure that looks like
	// a broken payload: the phone reports a good position, this server writes
	// valid sentences, and the Pager still reads 0, 0.
	go func() {
		err := cmd.Wait()
		select {
		case <-m.shutdown:
		default:
			warnf("gpsd exited (%v)", err)
		}
		close(exited)
	}()

	infof("Started gpsd on port %d serving %s", gpsdPort, m.slaveName)

	if err := verifyGPSD(m.slaveName, exited); err != nil {
		return err
	}

	infof("Confirmed gpsd is serving %s", m.slaveName)
	return nil
}

// supervise re-checks that the gpsd on the port is still ours, and takes it
// back when it is not. The Pager runs its own device-less gpsd and restores it
// whenever its services restart - that instance holds the port and answers
// clients while having nothing to read, so the position silently stops updating
// part way through a drive. Checking once at startup is not enough.
func (m *gpsdManager) supervise(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-m.shutdown:
			return
		case <-ticker.C:
		}

		if reason := m.unhealthy(); reason != "" {
			warnf("Reclaiming gpsd: %s", reason)
			if err := m.start(); err != nil {
				errorf("could not reclaim gpsd: %v", err)
			}
		}
	}
}

// unhealthy returns why gpsd needs restarting, or "" when all is well.
func (m *gpsdManager) unhealthy() string {
	m.mu.Lock()
	exited := m.exited
	m.mu.Unlock()

	if exited == nil {
		return "gpsd was never started"
	}

	select {
	case <-exited:
		return "gpsd is no longer running"
	default:
	}

	devices, err := queryGPSDDevices()
	if err != nil {
		return fmt.Sprintf("gpsd is not answering (%v)", err)
	}
	if !strings.Contains(devices, m.slaveName) {
		return fmt.Sprintf("another gpsd has taken port %d (%s)", gpsdPort, strings.TrimSpace(devices))
	}

	return ""
}

// stop ends supervision and shuts gpsd down.
func (m *gpsdManager) stop() {
	m.once.Do(func() { close(m.shutdown) })

	m.mu.Lock()
	cmd, exited := m.cmd, m.exited
	m.mu.Unlock()

	if cmd == nil || cmd.Process == nil {
		return
	}

	cmd.Process.Signal(syscall.SIGTERM)
	select {
	case <-exited:
	case <-time.After(2 * time.Second):
		cmd.Process.Kill()
		<-exited
	}
}

// stopExistingGPSD kills any gpsd that is already running and waits for the
// port to come free. killall returns before the process has gone, so starting
// immediately can leave the new gpsd dying on a bind error.
func stopExistingGPSD() {
	if err := exec.Command("killall", "gpsd").Run(); err != nil {
		// Nothing was running, which is the normal case.
		return
	}

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if !portInUse(gpsdPort) {
			return
		}
		time.Sleep(200 * time.Millisecond)
	}

	warnf("port %d is still in use - if the Pager supervises gpsd it has been respawned, and ours will not be able to bind", gpsdPort)
}

// portInUse reports whether something is listening on the port locally.
func portInUse(port int) bool {
	conn, err := net.DialTimeout("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(port)), time.Second)
	if err != nil {
		return false
	}
	conn.Close()
	return true
}

// verifyGPSD confirms that the gpsd answering on the port is serving our fake
// GPS device. A gpsd respawned by the Pager holds the port while watching the
// real serial GPS: it answers clients perfectly well and never reports a fix,
// which is indistinguishable from a broken payload without asking it.
func verifyGPSD(slaveName string, gpsdExited <-chan struct{}) error {
	deadline := time.Now().Add(5 * time.Second)

	for {
		select {
		case <-gpsdExited:
			return fmt.Errorf("gpsd is not running")
		default:
		}

		devices, err := queryGPSDDevices()
		if err == nil {
			if strings.Contains(devices, slaveName) {
				return nil
			}
			return fmt.Errorf("gpsd on port %d is serving another device, not %s (%s)",
				gpsdPort, slaveName, strings.TrimSpace(devices))
		}

		if time.Now().After(deadline) {
			return fmt.Errorf("could not confirm gpsd is serving %s: %w", slaveName, err)
		}

		time.Sleep(300 * time.Millisecond)
	}
}

// queryGPSDDevices returns gpsd's reply to ?DEVICES;.
func queryGPSDDevices() (string, error) {
	conn, err := net.DialTimeout("tcp", net.JoinHostPort("127.0.0.1", strconv.Itoa(gpsdPort)), 2*time.Second)
	if err != nil {
		return "", err
	}
	defer conn.Close()

	if err := conn.SetDeadline(time.Now().Add(3 * time.Second)); err != nil {
		return "", err
	}

	if _, err := conn.Write([]byte("?DEVICES;\n")); err != nil {
		return "", err
	}

	scanner := bufio.NewScanner(conn)
	for scanner.Scan() {
		if line := scanner.Text(); strings.Contains(line, "DEVICES") {
			return line, nil
		}
	}

	if err := scanner.Err(); err != nil {
		return "", err
	}

	return "", fmt.Errorf("gpsd did not answer ?DEVICES;")
}
