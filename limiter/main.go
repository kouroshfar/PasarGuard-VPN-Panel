// pg-site-limiter is a local SOCKS5 proxy that rate-limits connections per key.
//
// PasarGuard routes a user's traffic for limited sites here through two Xray SOCKS outbounds
// whose username is "k=<limit id>;r=<bytes per second>" (r=0 means unlimited). All connections
// with the same key share one token bucket per direction, and each new connection updates the
// bucket's rate. When the panel switches a limit to its slow outbound, the first new connection
// therefore also slows the connections that are already open, and switching back frees them.
package main

import (
	"encoding/binary"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"strconv"
	"strings"
	"sync"
	"time"
)

var (
	listenAddr  = flag.String("listen", "127.0.0.1:10808", "SOCKS5 listen address")
	dialTimeout = flag.Duration("dial-timeout", 10*time.Second, "outgoing connection timeout")
	idleTimeout = flag.Duration("idle-timeout", 5*time.Minute, "close connections idle this long")
	verbose     = flag.Bool("v", false, "log every connection")
)

// bucket is a token bucket shared by all connections of one key and direction.
type bucket struct {
	mu     sync.Mutex
	rate   int64 // bytes per second, <= 0 unlimited
	tokens float64
	last   time.Time
}

func (b *bucket) setRate(rate int64) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if rate != b.rate {
		b.rate = rate
		b.tokens = 0
		b.last = time.Now()
	}
}

// chunk is the most a connection should read at once so a write never needs more than a burst.
func (b *bucket) chunk(max int) int {
	b.mu.Lock()
	rate := b.rate
	b.mu.Unlock()
	if rate <= 0 {
		return max
	}
	n := int(burst(rate))
	if n > max {
		return max
	}
	return n
}

func burst(rate int64) float64 {
	// A quarter second of traffic keeps speed smooth without letting large spikes through.
	if b := float64(rate) / 4; b > 2048 {
		return b
	}
	return 2048
}

// take blocks until n bytes may pass.
func (b *bucket) take(n int) {
	for {
		b.mu.Lock()
		if b.rate <= 0 {
			b.mu.Unlock()
			return
		}
		now := time.Now()
		b.tokens += now.Sub(b.last).Seconds() * float64(b.rate)
		b.last = now
		if max := burst(b.rate); b.tokens > max {
			b.tokens = max
		}
		if b.tokens >= float64(n) {
			b.tokens -= float64(n)
			b.mu.Unlock()
			return
		}
		wait := time.Duration((float64(n) - b.tokens) / float64(b.rate) * float64(time.Second))
		b.mu.Unlock()
		if wait > 100*time.Millisecond {
			wait = 100 * time.Millisecond // re-check often so rate changes apply quickly
		}
		time.Sleep(wait)
	}
}

type limiter struct {
	up, down *bucket
	conns    int
	lastUsed time.Time
}

var (
	limitersMu sync.Mutex
	limiters   = map[string]*limiter{}
)

func acquire(key string, rate int64) *limiter {
	limitersMu.Lock()
	defer limitersMu.Unlock()
	l, ok := limiters[key]
	if !ok {
		l = &limiter{up: &bucket{rate: -1}, down: &bucket{rate: -1}}
		limiters[key] = l
	}
	l.up.setRate(rate)
	l.down.setRate(rate)
	l.conns++
	l.lastUsed = time.Now()
	return l
}

func release(l *limiter) {
	limitersMu.Lock()
	l.conns--
	l.lastUsed = time.Now()
	limitersMu.Unlock()
}

func gcLimiters() {
	for range time.Tick(time.Minute) {
		limitersMu.Lock()
		for key, l := range limiters {
			if l.conns == 0 && time.Since(l.lastUsed) > 10*time.Minute {
				delete(limiters, key)
			}
		}
		limitersMu.Unlock()
	}
}

// parseUser reads "k=<key>;r=<rate>" from the SOCKS username.
func parseUser(user string) (key string, rate int64) {
	for _, part := range strings.Split(user, ";") {
		k, v, _ := strings.Cut(strings.TrimSpace(part), "=")
		switch k {
		case "k":
			key = v
		case "r":
			rate, _ = strconv.ParseInt(v, 10, 64)
		}
	}
	return key, rate
}

func readFull(c net.Conn, n int) ([]byte, error) {
	buf := make([]byte, n)
	_, err := io.ReadFull(c, buf)
	return buf, err
}

// handshake runs the SOCKS5 greeting and CONNECT request and returns the target and username.
func handshake(c net.Conn) (target, user string, err error) {
	hdr, err := readFull(c, 2)
	if err != nil {
		return
	}
	if hdr[0] != 5 {
		return "", "", errors.New("not SOCKS5")
	}
	methods, err := readFull(c, int(hdr[1]))
	if err != nil {
		return
	}
	method := byte(0xff)
	for _, m := range methods {
		if m == 2 {
			method = 2
			break
		}
		if m == 0 {
			method = 0
		}
	}
	if _, err = c.Write([]byte{5, method}); err != nil {
		return
	}
	switch method {
	case 0xff:
		return "", "", errors.New("no acceptable auth method")
	case 2:
		var b []byte
		if b, err = readFull(c, 2); err != nil {
			return
		}
		var u []byte
		if u, err = readFull(c, int(b[1])); err != nil {
			return
		}
		if b, err = readFull(c, 1); err != nil {
			return
		}
		if _, err = readFull(c, int(b[0])); err != nil {
			return
		}
		user = string(u)
		if _, err = c.Write([]byte{1, 0}); err != nil {
			return
		}
	}

	req, err := readFull(c, 4)
	if err != nil {
		return
	}
	if req[1] != 1 {
		c.Write([]byte{5, 7, 0, 1, 0, 0, 0, 0, 0, 0}) // command not supported
		return "", "", fmt.Errorf("unsupported command %d", req[1])
	}
	var host string
	switch req[3] {
	case 1:
		var ip []byte
		if ip, err = readFull(c, 4); err != nil {
			return
		}
		host = net.IP(ip).String()
	case 4:
		var ip []byte
		if ip, err = readFull(c, 16); err != nil {
			return
		}
		host = net.IP(ip).String()
	case 3:
		var l []byte
		if l, err = readFull(c, 1); err != nil {
			return
		}
		var name []byte
		if name, err = readFull(c, int(l[0])); err != nil {
			return
		}
		host = string(name)
	default:
		c.Write([]byte{5, 8, 0, 1, 0, 0, 0, 0, 0, 0}) // address type not supported
		return "", "", fmt.Errorf("unsupported address type %d", req[3])
	}
	p, err := readFull(c, 2)
	if err != nil {
		return
	}
	return net.JoinHostPort(host, strconv.Itoa(int(binary.BigEndian.Uint16(p)))), user, nil
}

type deadlineConn interface {
	net.Conn
	CloseWrite() error
}

// pipe copies src to dst through bucket b and half-closes dst at EOF.
func pipe(dst, src net.Conn, b *bucket, done chan<- struct{}) {
	defer func() { done <- struct{}{} }()
	buf := make([]byte, 32*1024)
	for {
		src.SetReadDeadline(time.Now().Add(*idleTimeout))
		n, err := src.Read(buf[:b.chunk(len(buf))])
		if n > 0 {
			b.take(n)
			if _, werr := dst.Write(buf[:n]); werr != nil {
				return
			}
		}
		if err != nil {
			if c, ok := dst.(deadlineConn); ok {
				c.CloseWrite()
			}
			return
		}
	}
}

func serve(c net.Conn) {
	defer c.Close()
	c.SetDeadline(time.Now().Add(30 * time.Second))
	target, user, err := handshake(c)
	if err != nil {
		if *verbose {
			log.Printf("handshake from %s: %v", c.RemoteAddr(), err)
		}
		return
	}
	c.SetDeadline(time.Time{})

	remote, err := net.DialTimeout("tcp", target, *dialTimeout)
	if err != nil {
		c.Write([]byte{5, 4, 0, 1, 0, 0, 0, 0, 0, 0}) // host unreachable
		if *verbose {
			log.Printf("dial %s: %v", target, err)
		}
		return
	}
	defer remote.Close()
	if _, err := c.Write([]byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0}); err != nil {
		return
	}

	key, rate := parseUser(user)
	if *verbose {
		log.Printf("%s key=%q rate=%d", target, key, rate)
	}
	l := acquire(key, rate)
	defer release(l)

	done := make(chan struct{}, 2)
	go pipe(remote, c, l.up, done)
	go pipe(c, remote, l.down, done)
	<-done
	<-done
}

func main() {
	flag.Parse()
	ln, err := net.Listen("tcp", *listenAddr)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("pg-site-limiter listening on %s", *listenAddr)
	go gcLimiters()
	for {
		c, err := ln.Accept()
		if err != nil {
			log.Printf("accept: %v", err)
			time.Sleep(100 * time.Millisecond)
			continue
		}
		go serve(c)
	}
}
