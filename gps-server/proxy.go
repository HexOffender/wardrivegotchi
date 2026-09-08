// An optional control proxy.
//
// The phone must keep this page in the foreground, or its GPS position stops
// updating. Thus a control panel cannot live on a second page: it lives on the
// GPS page, which is served here over HTTPS. A browser will not let an HTTPS
// page call a plain-HTTP address, so the page cannot reach the payload's own
// HTTP server directly. This server relays for it: the page calls same-origin
// HTTPS here, and this code forwards the call to the payload over localhost
// HTTP, which the browser never sees.
//
// The proxy is off unless -control-proxy names a base URL. Thus the GPS server
// on its own carries no control feature and no dependency on any payload; the
// payload turns this on.
package main

import (
	"bytes"
	"io"
	"net/http"
	"time"
)

// controlProxyBase is the base URL of the payload's HTTP API, or "" when the
// control proxy is off.
var controlProxyBase string

// proxyClient has a short timeout so a stalled payload cannot hold a request
// goroutine open on this server.
var proxyClient = &http.Client{Timeout: 5 * time.Second}

// registerControlProxy adds the control routes. /status answers even when the
// proxy is off, so the page can ask whether control exists and hide its panel.
func registerControlProxy(base string) {
	controlProxyBase = base

	http.HandleFunc("/status", handleStatus)
	http.HandleFunc("/control", handleControl)

	if base == "" {
		infof("Control proxy off (no -control-proxy)")
	} else {
		infof("Control proxy on, forwarding to %s", base)
	}
}

// handleStatus forwards GET /status to the payload's status endpoint. When the
// proxy is off, or the payload cannot be reached, it says so in a small JSON
// body rather than failing, because the page polls this and reads the flag.
func handleStatus(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	w.Header().Set("Content-Type", "application/json")

	if controlProxyBase == "" {
		io.WriteString(w, `{"available":false}`)
		return
	}

	resp, err := proxyClient.Get(controlProxyBase + "/api/status")
	if err != nil {
		io.WriteString(w, `{"available":true,"reachable":false}`)
		return
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {

		}
	}(resp.Body)
	io.Copy(w, resp.Body)
}

// handleControl forwards POST /control to the payload's command endpoint,
// carrying the token header and the body through unchanged. The token is
// checked by the payload, not here: this code only relays.
func handleControl(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}
	if controlProxyBase == "" {
		http.Error(w, `{"status":"error","message":"control is disabled"}`, http.StatusNotFound)
		return
	}

	// Buffer the body so the forwarded request carries a Content-Length. If we
	// pass r.Body straight through, Go sends it chunked with no Content-Length,
	// and the payload's http.server reads an empty body, so every command looks
	// like it has no action. See web_server.py._read_body.
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, `{"status":"error","message":"bad request"}`, http.StatusBadRequest)
		return
	}

	req, err := http.NewRequest(http.MethodPost, controlProxyBase+"/api/command", bytes.NewReader(body))
	if err != nil {
		http.Error(w, `{"status":"error","message":"bad gateway"}`, http.StatusBadGateway)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if token := r.Header.Get("X-Control-Token"); token != "" {
		req.Header.Set("X-Control-Token", token)
	}

	resp, err := proxyClient.Do(req)
	if err != nil {
		http.Error(w, `{"status":"error","message":"payload unreachable"}`, http.StatusBadGateway)
		return
	}
	defer func(Body io.ReadCloser) {
		err := Body.Close()
		if err != nil {

		}
	}(resp.Body)

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(resp.StatusCode)
	io.Copy(w, resp.Body)
}
