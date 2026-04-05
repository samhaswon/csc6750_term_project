const promptInput = document.getElementById('prompt');
const runButton = document.getElementById('run');
const clearButton = document.getElementById('clear');
const cards = document.getElementById('cards');
const status = document.getElementById('status');
const wakeToggleButton = document.getElementById('wake-toggle');
const wakeHint = document.getElementById('wake-hint');

const SpeechRecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const DEFAULT_WAKE_WORDS = ['hey home', 'ok home'];
const DEFAULT_COMMAND_TIMEOUT_MS = 8000;

let recognition = null;
let wakeEnabled = false;
let wakeShouldRestart = false;
let wakeWords = [...DEFAULT_WAKE_WORDS];
let wakeCommandTimeoutMs = DEFAULT_COMMAND_TIMEOUT_MS;
let showToolCallResults = true;
let awaitingCommandUntil = 0;
let lastProcessedFinal = '';
let lastProcessedAt = 0;
let currentSpeechAudio = null;
let currentSpeechUrl = null;

const MESSAGES = [
  'Accomplishing',
  'Actioning',
  'Actualizing',
  'Baking',
  'Brewing',
  'Calculating',
  'Cerebrating',
  'Churning',
  'Clauding',
  'Coalescing',
  'Cogitating',
  'Computing',
  'Conjuring',
  'Considering',
  'Cooking',
  'Crafting',
  'Creating',
  'Crunching',
  'Deliberating',
  'Determining',
  'Doing',
  'Effecting',
  'Finagling',
  'Forging',
  'Forming',
  'Generating',
  'Hatching',
  'Herding',
  'Honking',
  'Hustling',
  'Ideating',
  'Inferring',
  'Manifesting',
  'Marinating',
  'Moseying',
  'Mulling',
  'Mustering',
  'Musing',
  'Noodling',
  'Percolating',
  'Pondering',
  'Processing',
  'Puttering',
  'Reticulating',
  'Ruminating',
  'Schlepping',
  'Shucking',
  'Simmering',
  'Smooshing',
  'Spinning',
  'Stewing',
  'Synthesizing',
  'Thinking',
  'Transmuting',
  'Vibing',
  'Working',
];

const setStatus = (text) => {
  status.textContent = text;
};

const addCard = (title, content) => {
  const card = document.createElement('article');
  card.className = 'card';
  const meta = document.createElement('div');
  meta.className = 'meta';
  meta.textContent = title;
  const body = document.createElement('div');
  body.className = 'content';
  body.textContent = content;
  card.appendChild(meta);
  card.appendChild(body);
  cards.prepend(card);
};

const stopCurrentSpeech = () => {
  if (currentSpeechAudio) {
    currentSpeechAudio.pause();
    currentSpeechAudio = null;
  }
  if (currentSpeechUrl) {
    URL.revokeObjectURL(currentSpeechUrl);
    currentSpeechUrl = null;
  }
};

const speakResponse = async (text) => {
  const spokenText = String(text || '').trim();
  if (!spokenText) {
    return;
  }

  try {
    const response = await fetch('/api/speak', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: spokenText })
    });
    if (!response.ok) {
      return;
    }
    const audioBlob = await response.blob();
    stopCurrentSpeech();
    currentSpeechUrl = URL.createObjectURL(audioBlob);
    currentSpeechAudio = new Audio(currentSpeechUrl);
    await currentSpeechAudio.play();
  } catch (_error) {
    // Browser autoplay or transient network failure; keep UI responsive.
  }
};

const setWakeUiState = (mode) => {
  promptInput.classList.remove('wake-glow', 'wake-pulse');
  if (mode === 'listening') {
    wakeToggleButton.textContent = 'Listening...';
    return;
  }
  if (mode === 'listening-command') {
    wakeToggleButton.textContent = 'Listening for command...';
    promptInput.classList.add('wake-glow');
    return;
  }
  if (mode === 'sending') {
    wakeToggleButton.textContent = 'Command captured. Sending...';
    promptInput.classList.add('wake-pulse');
    return;
  }
  if (mode === 'unsupported') {
    wakeToggleButton.textContent = 'Wake Word Unsupported';
    return;
  }
  wakeToggleButton.textContent = 'Listen for Wake Word';
};

const updateWakeHint = () => {
  wakeHint.textContent = `Wake words: ${wakeWords.join(', ')}`;
};

const updateWakeButton = () => {
  if (!SpeechRecognitionCtor) {
    wakeToggleButton.disabled = true;
    setWakeUiState('unsupported');
    return;
  }
  wakeToggleButton.disabled = false;
  setWakeUiState(wakeEnabled ? 'listening' : 'idle');
};

const normalizeSpeech = (text) => {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
};

const findWakeWord = (normalizedText) => {
  for (const wakeWord of wakeWords) {
    if (normalizedText.includes(wakeWord)) {
      return wakeWord;
    }
  }
  return null;
};

const extractCommandAfterWake = (normalizedText, wakeWord) => {
  const wakeIndex = normalizedText.indexOf(wakeWord);
  if (wakeIndex === -1) {
    return '';
  }
  return normalizedText.slice(wakeIndex + wakeWord.length).trim();
};

const submitVoiceCommand = async (commandText) => {
  if (runButton.disabled) {
    addCard('Wake Word', 'Skipped voice command while a request was already running.');
    return;
  }
  promptInput.value = commandText;
  await runPrompt(commandText);
};

const processFinalTranscript = async (transcript) => {
  if (!wakeEnabled) {
    return;
  }

  const normalized = normalizeSpeech(transcript);
  if (!normalized) {
    return;
  }

  const currentTimeMs = Date.now();
  if (normalized === lastProcessedFinal && currentTimeMs - lastProcessedAt < 1500) {
    return;
  }
  lastProcessedFinal = normalized;
  lastProcessedAt = currentTimeMs;

  if (awaitingCommandUntil > 0 && currentTimeMs > awaitingCommandUntil) {
    awaitingCommandUntil = 0;
    setWakeUiState('listening');
  }

  const wakeWord = findWakeWord(normalized);
  if (wakeWord) {
    const commandAfterWake = extractCommandAfterWake(normalized, wakeWord);
    if (commandAfterWake) {
      awaitingCommandUntil = 0;
      setWakeUiState('sending');
      await submitVoiceCommand(commandAfterWake);
      setWakeUiState('listening');
      return;
    }
    awaitingCommandUntil = currentTimeMs + wakeCommandTimeoutMs;
    setWakeUiState('listening-command');
    return;
  }

  if (awaitingCommandUntil > currentTimeMs) {
    awaitingCommandUntil = 0;
    setWakeUiState('sending');
    await submitVoiceCommand(normalized);
    setWakeUiState('listening');
  }
};

const configureRecognition = () => {
  if (!SpeechRecognitionCtor) {
    return null;
  }
  const instance = new SpeechRecognitionCtor();
  instance.lang = 'en-US';
  instance.continuous = true;
  instance.interimResults = true;
  instance.maxAlternatives = 1;

  instance.onresult = async (event) => {
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      if (!event.results[index].isFinal) {
        continue;
      }
      const transcript = event.results[index][0].transcript.trim();
      if (!transcript) {
        continue;
      }
      await processFinalTranscript(transcript);
    }
  };

  instance.onerror = (event) => {
    const errorName = event.error || 'unknown';
    addCard('Wake Word', `Wake word error: ${errorName}`);
    wakeEnabled = false;
    wakeShouldRestart = false;
    awaitingCommandUntil = 0;
    updateWakeButton();
  };

  instance.onend = () => {
    if (!wakeShouldRestart) {
      wakeEnabled = false;
      updateWakeButton();
      return;
    }
    try {
      instance.start();
      setWakeUiState('listening');
    } catch (_error) {
      wakeEnabled = false;
      wakeShouldRestart = false;
      updateWakeButton();
    }
  };

  return instance;
};

const startWakeWord = async () => {
  if (!SpeechRecognitionCtor) {
    setWakeUiState('unsupported');
    return;
  }

  if (!recognition) {
    recognition = configureRecognition();
  }

  try {
    wakeShouldRestart = true;
    wakeEnabled = true;
    recognition.start();
    setWakeUiState('listening');
    updateWakeButton();
  } catch (_error) {
    wakeEnabled = false;
    wakeShouldRestart = false;
    addCard('Wake Word', 'Could not start wake word listener.');
    updateWakeButton();
  }
};

const stopWakeWord = () => {
  wakeShouldRestart = false;
  wakeEnabled = false;
  awaitingCommandUntil = 0;
  if (recognition) {
    recognition.stop();
  }
  setWakeUiState('idle');
  updateWakeButton();
};

const runPrompt = async (overridePrompt = null) => {
  const prompt = (overridePrompt ?? promptInput.value).trim();
  if (!prompt) {
    return;
  }

  runButton.disabled = true;
  setStatus(`${MESSAGES[Math.floor(Math.random() * MESSAGES.length)]}...`);
  addCard('Prompt', prompt);

  try {
    const response = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt })
    });
    const payload = await response.json();
    if (!response.ok) {
      addCard('Error', payload.error || 'Request failed');
    } else {
      addCard('Response', payload.response || '');
      await speakResponse(payload.response || '');
      if (showToolCallResults && payload.tool_call) {
        addCard('Tool Call', JSON.stringify(payload.tool_call, null, 2));
      }
      if (showToolCallResults && payload.tool_result) {
        addCard('Tool Result', JSON.stringify(payload.tool_result, null, 2));
      }
    }
  } catch (error) {
    addCard('Error', error.message);
  } finally {
    runButton.disabled = false;
    setStatus('Idle');
    if (wakeEnabled) {
      setWakeUiState(awaitingCommandUntil > Date.now() ? 'listening-command' : 'listening');
    }
  }
};

const loadWakeWordConfig = async () => {
  try {
    const response = await fetch('/api/wake_word_config');
    if (!response.ok) {
      updateWakeHint();
      return;
    }
    const payload = await response.json();
    if (Array.isArray(payload.wake_words) && payload.wake_words.length > 0) {
      wakeWords = payload.wake_words
        .map((item) => String(item).trim().toLowerCase())
        .filter((item) => item.length > 0);
      if (wakeWords.length === 0) {
        wakeWords = [...DEFAULT_WAKE_WORDS];
      }
    }
    if (Number.isInteger(payload.command_timeout_ms) && payload.command_timeout_ms > 0) {
      wakeCommandTimeoutMs = payload.command_timeout_ms;
    }
    if (typeof payload.show_tool_call_results === 'boolean') {
      showToolCallResults = payload.show_tool_call_results;
    }
  } catch (_error) {
    wakeWords = [...DEFAULT_WAKE_WORDS];
    wakeCommandTimeoutMs = DEFAULT_COMMAND_TIMEOUT_MS;
    showToolCallResults = true;
  }
  updateWakeHint();
};

runButton.addEventListener('click', () => {
  void runPrompt();
});

clearButton.addEventListener('click', () => {
  promptInput.value = '';
  cards.innerHTML = '';
  setStatus('Idle');
});

wakeToggleButton.addEventListener('click', () => {
  if (wakeEnabled) {
    stopWakeWord();
    return;
  }
  void startWakeWord();
});

void loadWakeWordConfig();
updateWakeButton();
updateWakeHint();
