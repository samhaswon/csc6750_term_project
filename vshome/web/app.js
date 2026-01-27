const grid = document.getElementById('device-grid');
const cardTemplate = document.getElementById('device-card-template');
const videoTemplate = document.getElementById('video-card-template');
const wsStatus = document.getElementById('ws-status');
const wsDot = document.getElementById('ws-dot');

let socket;
let deviceState = new Map();
let cardRefs = new Map();

const formatValue = (value) => {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toString() : value.toFixed(1);
  }
  if (typeof value === 'boolean') {
    return value ? 'On' : 'Off';
  }
  return String(value);
};

const setStatus = (connected) => {
  wsStatus.textContent = connected ? 'Connected' : 'Disconnected';
  wsDot.classList.toggle('connected', connected);
};

const sendSet = (id, state) => {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(
    JSON.stringify({
      type: 'set',
      id,
      state,
    })
  );
};

const currentStateFor = (id) => {
  return deviceState.get(id) || null;
};

const buildSwitch = (labelText, checked, onToggle) => {
  const wrapper = document.createElement('label');
  wrapper.className = 'switch';
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = checked;
  const text = document.createElement('span');
  text.textContent = labelText;
  wrapper.appendChild(input);
  wrapper.appendChild(text);
  input.addEventListener('click', (event) => {
    event.preventDefault();
    onToggle();
  });
  return { wrapper, input };
};

const buildSlider = (labelText, value, min, max, step, onChange) => {
  const container = document.createElement('div');
  container.className = 'slider';
  const badge = document.createElement('span');
  badge.className = 'badge';
  badge.textContent = labelText;
  const input = document.createElement('input');
  input.type = 'range';
  input.min = min;
  input.max = max;
  input.step = step;
  input.value = value;
  const display = document.createElement('div');
  display.className = 'pill';
  display.textContent = formatValue(value);
  container.appendChild(badge);
  container.appendChild(input);
  container.appendChild(display);
  input.addEventListener('change', (event) => {
    event.preventDefault();
    onChange(Number(input.value));
  });
  return { container, input, display };
};

const switchLabelFor = (device, isOn) => {
  if (device.kind === 'lock') {
    return isOn ? 'Locked' : 'Unlocked';
  }
  if (device.kind === 'doors') {
    return isOn ? 'Open' : 'Closed';
  }
  if (device.kind === 'vacuum') {
    return isOn ? 'Cleaning' : 'Docked';
  }
  return isOn ? 'On' : 'Off';
};

const indicatorLabelFor = (device, isOn) => {
  if (device.kind === 'lock') {
    return isOn ? 'Secured' : 'Unsecured';
  }
  if (device.kind === 'doors') {
    return isOn ? 'Open' : 'Closed';
  }
  if (device.kind === 'vacuum') {
    return isOn ? 'Cleaning' : 'Docked';
  }
  if (device.kind === 'toaster') {
    return isOn ? 'Toasting' : 'Idle';
  }
  return isOn ? 'On' : 'Off';
};

const renderDeviceCard = (device) => {
  const card = cardTemplate.content.cloneNode(true);
  const root = card.querySelector('.card');
  const name = card.querySelector('.device-name');
  const room = card.querySelector('.device-room');
  const body = card.querySelector('.device-body');

  name.textContent = device.name;
  room.textContent = device.room || 'Unassigned';

  const controls = [];

  const indicator = document.createElement('div');
  indicator.className = 'state-indicator';
  const indicatorDot = document.createElement('span');
  indicatorDot.className = 'state-dot';
  const indicatorText = document.createElement('span');
  indicator.appendChild(indicatorDot);
  indicator.appendChild(indicatorText);

  const updateBadge = (text) => {
    const badge = document.createElement('div');
    badge.className = 'pill';
    badge.textContent = text;
    body.appendChild(badge);
  };

  if (['toggle', 'toaster', 'vacuum'].includes(device.kind)) {
    body.appendChild(indicator);
    indicatorText.textContent = indicatorLabelFor(device, Boolean(device.state.on));
    indicatorDot.classList.toggle('on', Boolean(device.state.on));
    const { wrapper, input } = buildSwitch(
      switchLabelFor(device, Boolean(device.state.on)),
      Boolean(device.state.on),
      () => {
        const current = currentStateFor(device.id);
        sendSet(device.id, { on: !Boolean(current?.state?.on) });
      }
    );
    body.appendChild(wrapper);
    controls.push({ type: 'switch', input, key: 'on' });
    controls.push({ type: 'indicator', text: indicatorText, dot: indicatorDot, key: 'on' });
  } else if (device.kind === 'lock') {
    body.appendChild(indicator);
    indicatorText.textContent = indicatorLabelFor(device, Boolean(device.state.locked));
    indicatorDot.classList.toggle('on', Boolean(device.state.locked));
    const { wrapper, input } = buildSwitch(
      switchLabelFor(device, Boolean(device.state.locked)),
      Boolean(device.state.locked),
      () => {
        const current = currentStateFor(device.id);
        sendSet(device.id, { locked: !Boolean(current?.state?.locked) });
      }
    );
    body.appendChild(wrapper);
    controls.push({ type: 'switch', input, key: 'locked' });
    controls.push({ type: 'indicator', text: indicatorText, dot: indicatorDot, key: 'locked' });
  } else if (device.kind === 'sensor') {
    updateBadge(device.state.open ? 'Open' : 'Closed');
  } else if (device.kind === 'blind') {
    const { container, input, display } = buildSlider(
      'Position',
      Number(device.state.position || 0),
      0,
      100,
      5,
      (value) => sendSet(device.id, { position: value })
    );
    body.appendChild(container);
    controls.push({ type: 'slider', input, display, key: 'position' });
  } else if (device.kind === 'thermostat') {
    const { container, input, display } = buildSlider(
      'Temperature (°C)',
      Number(device.state.temperature || 20),
      10,
      30,
      0.5,
      (value) => sendSet(device.id, { temperature: value })
    );
    body.appendChild(container);
    controls.push({ type: 'slider', input, display, key: 'temperature' });
  } else if (device.kind === 'humidifier') {
    const { container, input, display } = buildSlider(
      'Humidity Level',
      Number(device.state.level || 40),
      0,
      100,
      5,
      (value) => sendSet(device.id, { level: value })
    );
    body.appendChild(container);
    controls.push({ type: 'slider', input, display, key: 'level' });
  } else if (device.kind === 'doors') {
    body.appendChild(indicator);
    indicatorText.textContent = indicatorLabelFor(device, Boolean(device.state.open));
    indicatorDot.classList.toggle('on', Boolean(device.state.open));
    const { wrapper, input } = buildSwitch(
      switchLabelFor(device, Boolean(device.state.open)),
      Boolean(device.state.open),
      () => {
        const current = currentStateFor(device.id);
        sendSet(device.id, { open: !Boolean(current?.state?.open) });
      }
    );
    body.appendChild(wrapper);
    controls.push({ type: 'switch', input, key: 'open' });
    controls.push({ type: 'indicator', text: indicatorText, dot: indicatorDot, key: 'open' });
  } else {
    updateBadge('No control defined');
  }

  if (device.kind === 'toggle') {
    root.classList.toggle('light-on', Boolean(device.state.on));
  }

  return { root, controls };
};

const applyDeviceUpdate = (device) => {
  deviceState.set(device.id, device);

  const ref = cardRefs.get(device.id);
  if (!ref) {
    return;
  }

  ref.controls.forEach((control) => {
    if (control.type === 'switch') {
      control.input.checked = Boolean(device.state[control.key]);
      control.input.nextSibling.textContent = switchLabelFor(device, control.input.checked);
    }
    if (control.type === 'indicator') {
      const isOn = Boolean(device.state[control.key]);
      control.text.textContent = indicatorLabelFor(device, isOn);
      control.dot.classList.toggle('on', isOn);
    }
    if (control.type === 'slider') {
      const value = Number(device.state[control.key] || 0);
      control.input.value = value;
      control.display.textContent = formatValue(value);
    }
  });

  if (device.kind === 'toggle') {
    ref.root.classList.toggle('light-on', Boolean(device.state.on));
  }

  if (device.kind === 'sensor') {
    const badge = ref.root.querySelector('.pill');
    if (badge) {
      badge.textContent = device.state.open ? 'Open' : 'Closed';
    }
  }
};

const groupDevicesByRoom = (devices) => {
  const rooms = new Map();
  const order = [];
  devices.forEach((device) => {
    const room = device.room || 'Unassigned';
    if (!rooms.has(room)) {
      rooms.set(room, []);
      order.push(room);
    }
    rooms.get(room).push(device);
  });
  return { rooms, order };
};

const renderDevices = (devices) => {
  grid.innerHTML = '';
  cardRefs.clear();
  deviceState = new Map(devices.map((device) => [device.id, device]));

  const { rooms, order } = groupDevicesByRoom(devices);
  let index = 0;

  order.forEach((roomName) => {
    const section = document.createElement('section');
    section.className = 'room-group';
    const title = document.createElement('h2');
    title.className = 'room-title';
    title.textContent = roomName;
    const roomGrid = document.createElement('div');
    roomGrid.className = 'room-grid';
    section.appendChild(title);
    section.appendChild(roomGrid);
    grid.appendChild(section);

    rooms.get(roomName).forEach((device) => {
      const { root, controls } = renderDeviceCard(device);
      root.style.animationDelay = `${Math.min(index * 0.03, 0.6)}s`;
      roomGrid.appendChild(root);
      cardRefs.set(device.id, { root, controls });
      index += 1;
    });
  });

  const mediaSection = document.createElement('section');
  mediaSection.className = 'room-group';
  const mediaTitle = document.createElement('h2');
  mediaTitle.className = 'room-title';
  mediaTitle.textContent = 'Media';
  const mediaGrid = document.createElement('div');
  mediaGrid.className = 'room-grid';
  mediaSection.appendChild(mediaTitle);
  mediaSection.appendChild(mediaGrid);
  mediaGrid.appendChild(videoTemplate.content.cloneNode(true));
  grid.appendChild(mediaSection);
};

const connect = () => {
  socket = new WebSocket(`${window.location.origin.replace('http', 'ws')}/ws`);

  socket.addEventListener('open', () => setStatus(true));
  socket.addEventListener('close', () => setStatus(false));
  socket.addEventListener('error', () => setStatus(false));

  socket.addEventListener('message', (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === 'state') {
      renderDevices(payload.devices || []);
    }
    if (payload.type === 'update' && payload.device) {
      applyDeviceUpdate(payload.device);
    }
  });
};

connect();
