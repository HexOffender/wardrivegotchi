package main

import (
	"testing"
	"time"

	"github.com/creack/pty"
)

// The hazard this guards: with nothing reading the pty, a direct write blocks
// forever and takes the HTTP handler down with it. submit must always return.
func TestFeedNeverBlocksWhenNothingReads(t *testing.T) {
	master, slave, err := pty.Open()
	if err != nil {
		t.Fatal(err)
	}
	defer master.Close()
	defer slave.Close()

	f := newGPSFeed(master)
	go f.run()
	defer f.close()

	sentence := []byte("$GPRMC,020013.07,A,4525.593953,N,07541.158849,W,,,050926,,,A*4B\r\n")

	done := make(chan struct{})
	go func() {
		for i := 0; i < feedQueueDepth*20; i++ {
			f.submit(sentence)
		}
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("submit blocked - the handler would have hung")
	}

	if f.dropped.Load() == 0 {
		t.Error("expected drops once the queue filled with no reader")
	}
	t.Logf("%d submitted, %d dropped, none blocked", feedQueueDepth*20, f.dropped.Load())
}

func TestFeedWritesWhenSomethingReads(t *testing.T) {
	master, slave, err := pty.Open()
	if err != nil {
		t.Fatal(err)
	}
	defer master.Close()
	defer slave.Close()

	// Stand in for gpsd.
	go func() {
		b := make([]byte, 512)
		for {
			if _, err := slave.Read(b); err != nil {
				return
			}
		}
	}()

	f := newGPSFeed(master)
	go f.run()
	defer f.close()

	for i := 0; i < 5; i++ {
		if !f.submit([]byte("$GPRMC,test\r\n")) {
			t.Fatalf("submit %d was rejected with a reader attached", i)
		}
	}

	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if f.written.Load() == 5 {
			return
		}
		time.Sleep(50 * time.Millisecond)
	}
	t.Fatalf("only %d of 5 sentences reached the device", f.written.Load())
}
