package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
	"gopkg.in/yaml.v3"
)

type Device struct {
	ID    string                 `yaml:"id" json:"id"`
	Name  string                 `yaml:"name" json:"name"`
	Kind  string                 `yaml:"kind" json:"kind"`
	Room  string                 `yaml:"room" json:"room"`
	State map[string]interface{} `yaml:"state" json:"state"`
}

type DeviceCatalog struct {
	Devices []*Device `yaml:"devices"`
}

type Store struct {
	mu      sync.RWMutex
	devices map[string]*Device
	order   []string
}

var store *Store
var hub *Hub

func NewStore(devices []*Device) *Store {
	deviceMap := make(map[string]*Device, len(devices))
	order := make([]string, 0, len(devices))
	for _, device := range devices {
		copyDevice := *device
		copyDevice.State = copyState(device.State)
		deviceMap[device.ID] = &copyDevice
		order = append(order, device.ID)
	}
	return &Store{devices: deviceMap, order: order}
}

func (s *Store) List() []*Device {
	s.mu.RLock()
	defer s.mu.RUnlock()
	devices := make([]*Device, 0, len(s.order))
	for _, id := range s.order {
		device, ok := s.devices[id]
		if !ok {
			continue
		}
		copyDevice := *device
		copyDevice.State = copyState(device.State)
		devices = append(devices, &copyDevice)
	}
	return devices
}

func (s *Store) Get(id string) (*Device, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	device, ok := s.devices[id]
	if !ok {
		return nil, false
	}
	copyDevice := *device
	copyDevice.State = copyState(device.State)
	return &copyDevice, true
}

func (s *Store) Update(id string, state map[string]interface{}) (*Device, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	device, ok := s.devices[id]
	if !ok {
		return nil, fmt.Errorf("device not found: %s", id)
	}
	for key, value := range state {
		device.State[key] = normalizeValue(device.Kind, key, value)
	}
	copyDevice := *device
	copyDevice.State = copyState(device.State)
	return &copyDevice, nil
}

func copyState(state map[string]interface{}) map[string]interface{} {
	if state == nil {
		return map[string]interface{}{}
	}
	copyMap := make(map[string]interface{}, len(state))
	for key, value := range state {
		copyMap[key] = value
	}
	return copyMap
}

func normalizeValue(kind, key string, value interface{}) interface{} {
	switch kind {
	case "blind", "humidifier":
		if key == "position" || key == "level" {
			return clampToInt(value, 0, 100)
		}
	case "thermostat":
		if key == "temperature" {
			return clampToFloat(value, 10, 30)
		}
	case "toggle", "lock", "sensor", "toaster", "doors", "vacuum":
		if key == "on" || key == "open" || key == "locked" {
			return toBool(value)
		}
		if key == "mode" {
			if mode, ok := value.(string); ok {
				return strings.TrimSpace(mode)
			}
		}
	}
	return value
}

func clampToInt(value interface{}, min, max int) int {
	switch number := value.(type) {
	case int:
		return clampInt(number, min, max)
	case int64:
		return clampInt(int(number), min, max)
	case float64:
		return clampInt(int(number+0.5), min, max)
	case float32:
		return clampInt(int(number+0.5), min, max)
	case json.Number:
		if parsed, err := number.Int64(); err == nil {
			return clampInt(int(parsed), min, max)
		}
	}
	return min
}

func clampToFloat(value interface{}, min, max float64) float64 {
	switch number := value.(type) {
	case float64:
		return clampFloat(number, min, max)
	case float32:
		return clampFloat(float64(number), min, max)
	case int:
		return clampFloat(float64(number), min, max)
	case int64:
		return clampFloat(float64(number), min, max)
	case json.Number:
		if parsed, err := number.Float64(); err == nil {
			return clampFloat(parsed, min, max)
		}
	}
	return min
}

func clampInt(value, min, max int) int {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}

func clampFloat(value, min, max float64) float64 {
	if value < min {
		return min
	}
	if value > max {
		return max
	}
	return value
}

func toBool(value interface{}) bool {
	switch v := value.(type) {
	case bool:
		return v
	case string:
		return strings.EqualFold(v, "true") || v == "1" || strings.EqualFold(v, "on")
	case int:
		return v != 0
	case int64:
		return v != 0
	case float64:
		return v != 0
	default:
		return false
	}
}

type WSMessage struct {
	Type    string    `json:"type"`
	Device  *Device   `json:"device,omitempty"`
	Devices []*Device `json:"devices,omitempty"`
	Error   string    `json:"error,omitempty"`
}

type WSSetMessage struct {
	Type  string                 `json:"type"`
	ID    string                 `json:"id"`
	State map[string]interface{} `json:"state"`
}

type Hub struct {
	mu        sync.Mutex
	clients   map[*websocket.Conn]struct{}
	upgrader  websocket.Upgrader
	store     *Store
	broadcast chan *Device
}

func NewHub(store *Store) *Hub {
	return &Hub{
		clients: make(map[*websocket.Conn]struct{}),
		upgrader: websocket.Upgrader{
			ReadBufferSize:  1024,
			WriteBufferSize: 1024,
			CheckOrigin: func(r *http.Request) bool {
				return true
			},
		},
		store:     store,
		broadcast: make(chan *Device, 32),
	}
}

func (h *Hub) Run() {
	for device := range h.broadcast {
		message := WSMessage{Type: "update", Device: device}
		h.broadcastMessage(message)
	}
}

func (h *Hub) broadcastMessage(message WSMessage) {
	h.mu.Lock()
	defer h.mu.Unlock()
	for client := range h.clients {
		if err := client.WriteJSON(message); err != nil {
			_ = client.Close()
			delete(h.clients, client)
		}
	}
}

func (h *Hub) HandleWS(w http.ResponseWriter, r *http.Request) {
	conn, err := h.upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("websocket upgrade failed: %v", err)
		return
	}
	h.register(conn)
	defer h.unregister(conn)

	initial := WSMessage{Type: "state", Devices: h.store.List()}
	if err := conn.WriteJSON(initial); err != nil {
		log.Printf("websocket initial send failed: %v", err)
		return
	}

	conn.SetReadLimit(4096)
	_ = conn.SetReadDeadline(time.Now().Add(5 * time.Minute))
	conn.SetPongHandler(func(string) error {
		return conn.SetReadDeadline(time.Now().Add(5 * time.Minute))
	})

	for {
		var incoming WSSetMessage
		if err := conn.ReadJSON(&incoming); err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Printf("websocket read error: %v", err)
			}
			return
		}
		if incoming.Type != "set" {
			_ = conn.WriteJSON(WSMessage{Type: "error", Error: "unsupported message type"})
			continue
		}
		if incoming.ID == "" {
			_ = conn.WriteJSON(WSMessage{Type: "error", Error: "missing device id"})
			continue
		}
		updated, err := h.store.Update(incoming.ID, incoming.State)
		if err != nil {
			_ = conn.WriteJSON(WSMessage{Type: "error", Error: err.Error()})
			continue
		}
		h.broadcast <- updated
	}
}

func (h *Hub) register(conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.clients[conn] = struct{}{}
}

func (h *Hub) unregister(conn *websocket.Conn) {
	h.mu.Lock()
	defer h.mu.Unlock()
	delete(h.clients, conn)
	_ = conn.Close()
}

func main() {
	devices, err := loadDevices("devices.yaml")
	if err != nil {
		log.Fatalf("failed to load devices: %v", err)
	}
	store = NewStore(devices)
	hub = NewHub(store)
	go hub.Run()

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", hub.HandleWS)
	mux.HandleFunc("/api/devices", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		writeJSON(w, http.StatusOK, store.List())
	})
	mux.HandleFunc("/api/devices/", func(w http.ResponseWriter, r *http.Request) {
		id := strings.TrimPrefix(r.URL.Path, "/api/devices/")
		if id == "" {
			writeError(w, http.StatusBadRequest, "missing device id")
			return
		}
		switch r.Method {
		case http.MethodGet:
			device, ok := store.Get(id)
			if !ok {
				writeError(w, http.StatusNotFound, "device not found")
				return
			}
			writeJSON(w, http.StatusOK, device)
		case http.MethodPut:
			var payload struct {
				State map[string]interface{} `json:"state"`
			}
			if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
				writeError(w, http.StatusBadRequest, "invalid json")
				return
			}
			if len(payload.State) == 0 {
				writeError(w, http.StatusBadRequest, "missing state")
				return
			}
			updated, err := store.Update(id, payload.State)
			if err != nil {
				writeError(w, http.StatusNotFound, err.Error())
				return
			}
			hub.broadcast <- updated
			writeJSON(w, http.StatusOK, updated)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
	})

	webDir := http.Dir("web")
	mux.Handle("/", http.FileServer(webDir))

	addr := ":8080"
	log.Printf("virtual smart home running at http://localhost%s", addr)
	if err := http.ListenAndServe(addr, logRequests(mux)); err != nil {
		log.Fatalf("server error: %v", err)
	}
}

func loadDevices(path string) ([]*Device, error) {
	file, err := os.Open(filepath.Clean(path))
	if err != nil {
		return nil, err
	}
	defer file.Close()

	var catalog DeviceCatalog
	decoder := yaml.NewDecoder(file)
	if err := decoder.Decode(&catalog); err != nil {
		return nil, err
	}
	if len(catalog.Devices) == 0 {
		return nil, errors.New("no devices defined")
	}
	seen := make(map[string]struct{}, len(catalog.Devices))
	for _, device := range catalog.Devices {
		if device.ID == "" || device.Name == "" || device.Kind == "" {
			return nil, errors.New("device missing id, name, or kind")
		}
		if _, ok := seen[device.ID]; ok {
			return nil, fmt.Errorf("duplicate device id: %s", device.ID)
		}
		seen[device.ID] = struct{}{}
		if device.State == nil {
			device.State = map[string]interface{}{}
		}
	}
	return catalog.Devices, nil
}

func writeJSON(w http.ResponseWriter, status int, payload interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(payload); err != nil {
		log.Printf("write json error: %v", err)
	}
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func logRequests(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		log.Printf("%s %s", r.Method, r.URL.Path)
		next.ServeHTTP(w, r)
	})
}
