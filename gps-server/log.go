// Logging. Quiet by default and loud on request.
//
// /tmp is a RAM-backed filesystem on the Pager, and this payload runs beside a
// scanner that wants that memory. Logging every NMEA sentence for a multi-hour
// drive writes megabytes into RAM to say the same thing a thousand times, so
// per-sentence detail lives behind -v and the steady state is one summary line
// a minute.
package main

import (
	"log"
	"os"
)

var verbose bool

var (
	infoLog  = log.New(os.Stdout, "", log.LstdFlags)
	warnLog  = log.New(os.Stderr, "WARN  ", log.LstdFlags)
	errorLog = log.New(os.Stderr, "ERROR ", log.LstdFlags)
	debugLog = log.New(os.Stdout, "debug ", log.LstdFlags)
)

func infof(format string, args ...any)  { infoLog.Printf(format, args...) }
func warnf(format string, args ...any)  { warnLog.Printf(format, args...) }
func errorf(format string, args ...any) { errorLog.Printf(format, args...) }

func debugf(format string, args ...any) {
	if verbose {
		debugLog.Printf(format, args...)
	}
}
