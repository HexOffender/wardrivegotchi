// mobile2gps relays a phone's browser location to gpsd.
//
// It serves an HTTPS page the phone opens, converts each reported position into
// an NMEA GPRMC sentence, and writes it to a pseudo-terminal that gpsd reads as
// an ordinary serial GPS. Everything downstream - the Pager's GPS screen, a
// wardriving payload, anything speaking to gpsd - sees a normal receiver.
//
// HTTPS is not decorative: the browser Geolocation API refuses to run outside a
// secure context, so the page has to be served over TLS even on a local link.
package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"syscall"
	"time"

	"github.com/creack/pty"
)

const (
	httpsPort = 1993
	gpsdPort  = 2947
	indexFile = "index.html"
	certFile  = "cert.pem"
	keyFile   = "key.pem"

	// managementIP is the Pager's address on the Management AP. It is also the
	// address handed out over the USB-C Ethernet interface, so it stays in the
	// certificate even when that interface is down at startup.
	managementIP = "172.16.52.1"

	// Positions less accurate than this are sent as void sentences, which gpsd
	// reports as no fix. Indoors, or on a link with no route to the internet,
	// a phone's accuracy degrades badly and those positions are not worth
	// recording against a scan.
	defaultMaxAccuracy = 100.0
)

var (
	server      *http.Server
	feed        *gpsFeed
	maxAccuracy float64

	bufferPool = sync.Pool{
		New: func() any { return new(bytes.Buffer) },
	}
)

func main() {
	showURLs := flag.Bool("urls", false, "print every address the server can be reached at, then exit")
	flag.BoolVar(&verbose, "v", false, "log every position and NMEA sentence")
	flag.Float64Var(&maxAccuracy, "max-accuracy", defaultMaxAccuracy,
		"metres of accuracy beyond which a position is reported as no fix")
	controlProxy := flag.String("control-proxy", "",
		"base URL of a payload HTTP API to expose scan controls through (off when empty)")
	noGPS := flag.Bool("no-gps", false,
		"serve the page and controls only; do not open a device or manage gpsd "+
			"(for when a separate GPS module feeds gpsd)")
	flag.Parse()

	// The payload uses -urls to show the right address for whichever transport
	// is connected, rather than assuming the Management AP.
	if *showURLs {
		for _, url := range reachableURLs() {
			fmt.Println(url)
		}
		return
	}

	tlsCert, err := loadOrGenerateCert()
	if err != nil {
		errorLog.Fatalf("loading or generating the certificate: %v", err)
	}

	// GPS setup, unless -no-gps. In control-only mode a separate GPS module
	// feeds gpsd, so this server must not open a device or touch gpsd at all;
	// it only serves the page and relays controls.
	var (
		master *os.File
		slave  *os.File
		gpsd   *gpsdManager
	)
	if *noGPS {
		infof("Running without GPS: page and controls only")
	} else {
		// The fake GPS device: gpsd reads the slave, we write the master.
		var err error
		master, slave, err = pty.Open()
		if err != nil {
			errorLog.Fatalf("opening the fake GPS device: %v", err)
		}
		slaveName := slave.Name()

		// gpsd drops privileges after startup, so the device has to be readable
		// by more than root.
		if err := os.Chmod(slaveName, 0666); err != nil {
			warnf("could not chmod %s: %v", slaveName, err)
		}
		infof("Created fake GPS device: %s", slaveName)

		feed = newGPSFeed(master)
		go feed.run()
		if !verbose {
			go feed.summarise(summaryInterval)
		}

		// Run gpsd against that device, and keep checking it is still ours: the
		// Pager restores its own device-less gpsd whenever its services restart,
		// which otherwise ends a drive's position updates silently.
		gpsd = newGPSDManager(slaveName)
		if err := gpsd.start(); err != nil {
			warnf("%v", err)
		}
		go gpsd.supervise(superviseInterval)
	}

	http.HandleFunc("/", handleRequest)
	registerControlProxy(*controlProxy)

	server = &http.Server{
		Addr:              fmt.Sprintf(":%d", httpsPort),
		TLSConfig:         &tls.Config{Certificates: []tls.Certificate{tlsCert}},
		ReadHeaderTimeout: 10 * time.Second,
	}

	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigChan
		infof("Shutting down...")

		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := server.Shutdown(ctx); err != nil {
			warnf("shutting down the HTTP server: %v", err)
		}

		if gpsd != nil {
			gpsd.stop()
		}
		if feed != nil {
			feed.close()
		}
		// The slave is held open for the life of the process: closing it early
		// can leave gpsd unable to reopen the device.
		if master != nil {
			err := master.Close()
			if err != nil {
				return
			}
		}
		if slave != nil {
			err := slave.Close()
			if err != nil {
				return
			}
		}
		os.Exit(0)
	}()

	infof("HTTPS server listening on port %d", httpsPort)
	logReachableURLs()

	if err := server.ListenAndServeTLS("", ""); err != http.ErrServerClosed {
		errorLog.Fatalf("HTTPS server: %v", err)
	}
}

func handleRequest(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		serveIndex(w, r)
	case http.MethodPost:
		handleGPSData(w, r)
	default:
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
	}
}

func serveIndex(w http.ResponseWriter, r *http.Request) {
	if r.URL.Path == "/" || r.URL.Path == "/index.html" {
		http.ServeFile(w, r, indexFile)
		return
	}
	http.NotFound(w, r)
}

// handleGPSData converts the positions in a form post into NMEA sentences and
// queues them for the GPS device. It does not write to the device itself - see
// gpsFeed for why that must not happen on a request goroutine.
func handleGPSData(w http.ResponseWriter, r *http.Request) {
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {

		}
	}(r.Body)
	defer func() {
		r.Form = nil
		r.PostForm = nil
	}()

	if err := r.ParseForm(); err != nil {
		http.Error(w, "Bad request", http.StatusBadRequest)
		return
	}

	lats := r.Form["Lat"]
	lons := r.Form["Lon"]
	accs := r.Form["Acc"]
	times := r.Form["Time"]

	if len(lats) == 0 {
		http.Error(w, "No GPS data", http.StatusBadRequest)
		return
	}

	// In control-only mode there is no device to feed. Accept and ignore, so a
	// stale page that still posts does not error-spam.
	if feed == nil {
		w.WriteHeader(http.StatusOK)
		return
	}

	buf := bufferPool.Get().(*bytes.Buffer)
	defer func() {
		buf.Reset()
		bufferPool.Put(buf)
	}()

	queued := 0
	for i := range lats {
		if i >= len(lons) {
			continue
		}

		lat, err := strconv.ParseFloat(lats[i], 64)
		if err != nil {
			continue
		}
		lon, err := strconv.ParseFloat(lons[i], 64)
		if err != nil {
			continue
		}

		ts := time.Now()
		if i < len(times) {
			if msec, err := strconv.ParseInt(times[i], 10, 64); err == nil {
				ts = time.UnixMilli(msec)
			}
		}

		// A position the phone is not confident about is sent as void, so gpsd
		// reports no fix rather than a plausible-looking wrong location.
		valid, faa := "V", "N"
		accuracy := -1.0
		if i < len(accs) {
			if acc, err := strconv.ParseFloat(accs[i], 64); err == nil {
				accuracy = acc
				if acc <= maxAccuracy {
					valid, faa = "A", "A"
				}
			}
		}

		buf.Reset()
		buildGPRMC(buf, lat, lon, ts, valid, faa)

		// The buffer is reused, so the queue gets its own copy.
		sentence := make([]byte, buf.Len())
		copy(sentence, buf.Bytes())

		if feed.submit(sentence) {
			queued++
			if valid == "A" {
				feed.noteFix(lat, lon)
			}
			debugf("%s", bytes.TrimRight(sentence, "\r\n"))
		} else {
			warnf("position queue is full, dropping an update - is gpsd reading the device?")
		}

		if verbose && accuracy >= 0 && valid == "V" {
			debugf("accuracy %.1fm is worse than %.0fm, reported as no fix", accuracy, maxAccuracy)
		}
	}

	debugf("queued %d of %d position(s)", queued, len(lats))
	w.WriteHeader(http.StatusOK)
}
