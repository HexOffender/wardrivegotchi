// Turning browser positions into something gpsd will read.
package main

import (
	"bytes"
	"fmt"
	"os"
	"sync"
	"sync/atomic"
	"time"
)

const (
	// Sentences are spaced slightly rather than written back to back, which
	// keeps gpsd's parser from seeing them as one burst.
	writePad = 33 * time.Millisecond

	// Queue depth. A few seconds of updates is plenty: the phone sends roughly
	// one position a second, and anything older than that is not worth
	// delivering to a scanner recording where it is right now.
	feedQueueDepth = 32

	// How often to summarise throughput when not running verbose.
	summaryInterval = 60 * time.Second
)

// gpsFeed serializes writes to the fake GPS device.
//
// Writing straight from the HTTP handler is a hazard. When nothing is reading
// the pty - gpsd has died, or the Pager's own gpsd has taken the port - a write
// blocks indefinitely, and write deadlines do not take effect on a pty master
// (verified: the write simply never returns). A blocked handler holds its
// request open and the next update queues behind it, so one dead daemon stalls
// the whole server.
//
// One writer goroutine behind a bounded queue keeps the handler non-blocking.
// If the queue fills, sentences are dropped and counted - the honest outcome
// when nothing is listening, and visible in the summary rather than silent.
type gpsFeed struct {
	pty   *os.File
	queue chan []byte

	written atomic.Uint64
	dropped atomic.Uint64
	failed  atomic.Uint64

	lastFix atomic.Pointer[string]

	stop     chan struct{}
	stopOnce sync.Once
}

func newGPSFeed(pty *os.File) *gpsFeed {
	return &gpsFeed{
		pty:   pty,
		queue: make(chan []byte, feedQueueDepth),
		stop:  make(chan struct{}),
	}
}

// submit queues a sentence, reporting whether it was accepted. It never blocks.
func (f *gpsFeed) submit(sentence []byte) bool {
	select {
	case f.queue <- sentence:
		return true
	default:
		f.dropped.Add(1)
		return false
	}
}

// run writes queued sentences to the pty until stopped.
func (f *gpsFeed) run() {
	for {
		select {
		case <-f.stop:
			return
		case sentence := <-f.queue:
			if _, err := f.pty.Write(sentence); err != nil {
				f.failed.Add(1)
				errorf("writing to the GPS device: %v", err)
			} else {
				f.written.Add(1)
			}

			select {
			case <-f.stop:
				return
			case <-time.After(writePad):
			}
		}
	}
}

// summarise logs throughput periodically, so a quiet run still shows progress
// and a dropping queue is visible without turning on per-sentence logging.
func (f *gpsFeed) summarise(interval time.Duration) {
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	var lastWritten uint64

	for {
		select {
		case <-f.stop:
			return
		case <-ticker.C:
		}

		written := f.written.Load()
		since := written - lastWritten
		lastWritten = written

		if since == 0 && f.dropped.Load() == 0 {
			infof("no position updates in the last %s - is the page still open on the phone?",
				interval.Round(time.Second))
			continue
		}

		msg := fmt.Sprintf("%d positions in the last %s (%d total)",
			since, interval.Round(time.Second), written)
		if fix := f.lastFix.Load(); fix != nil {
			msg += ", last " + *fix
		}
		if dropped := f.dropped.Load(); dropped > 0 {
			msg += fmt.Sprintf(", %d dropped", dropped)
		}
		if failed := f.failed.Load(); failed > 0 {
			msg += fmt.Sprintf(", %d write errors", failed)
		}
		infof("%s", msg)
	}
}

// noteFix records the most recent accepted position for the summary line.
func (f *gpsFeed) noteFix(lat, lon float64) {
	s := fmt.Sprintf("%.5f,%.5f", lat, lon)
	f.lastFix.Store(&s)
}

func (f *gpsFeed) close() {
	f.stopOnce.Do(func() { close(f.stop) })
}

// buildGPRMC writes an NMEA GPRMC sentence for a position into buf.
func buildGPRMC(buf *bytes.Buffer, lat, lon float64, ts time.Time, valid, faa string) {
	// NMEA carries UTC. time.UnixMilli returns local time, so formatting it
	// directly puts the Pager's timezone offset into every sentence.
	ts = ts.UTC()

	buf.WriteByte('$')

	// Everything after '$' is covered by the checksum.
	bodyStart := buf.Len()

	buf.WriteString("GPRMC,")

	// Time: HHMMSS.ss
	buf.WriteString(ts.Format("150405"))
	buf.WriteByte('.')
	fmt.Fprintf(buf, "%02d", ts.Nanosecond()/10000000)
	buf.WriteByte(',')

	buf.WriteString(valid)
	buf.WriteByte(',')

	// Latitude: DDMM.MMMMMM,N/S
	latHemi := "N"
	if lat < 0 {
		latHemi = "S"
		lat = -lat
	}
	latDeg := int(lat)
	latMin := (lat - float64(latDeg)) * 60.0
	fmt.Fprintf(buf, "%02d%09.6f,%s,", latDeg, latMin, latHemi)

	// Longitude: DDDMM.MMMMMM,E/W
	lonHemi := "E"
	if lon < 0 {
		lonHemi = "W"
		lon = -lon
	}
	lonDeg := int(lon)
	lonMin := (lon - float64(lonDeg)) * 60.0
	fmt.Fprintf(buf, "%03d%09.6f,%s,,,", lonDeg, lonMin, lonHemi)

	// Date, then the empty magnetic variation fields, then the FAA mode.
	buf.WriteString(ts.Format("020106"))
	buf.WriteString(",,,")
	buf.WriteString(faa)

	body := buf.Bytes()[bodyStart:]
	checksum := byte(0)
	for i := 0; i < len(body); i++ {
		checksum ^= body[i]
	}

	fmt.Fprintf(buf, "*%02X\r\n", checksum)
}
