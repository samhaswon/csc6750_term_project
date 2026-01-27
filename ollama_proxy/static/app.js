const promptInput = document.getElementById('prompt');
const runButton = document.getElementById('run');
const clearButton = document.getElementById('clear');
const cards = document.getElementById('cards');
const status = document.getElementById('status');

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

const runPrompt = async () => {
  const prompt = promptInput.value.trim();
  if (!prompt) {
    return;
  }
  runButton.disabled = true;
  setStatus('Generating...');
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
      if (payload.tool_call) {
        addCard('Tool Call', JSON.stringify(payload.tool_call, null, 2));
      }
      if (payload.tool_result) {
        addCard('Tool Result', JSON.stringify(payload.tool_result, null, 2));
      }
    }
  } catch (error) {
    addCard('Error', error.message);
  } finally {
    runButton.disabled = false;
    setStatus('Idle');
  }
};

runButton.addEventListener('click', runPrompt);
clearButton.addEventListener('click', () => {
  promptInput.value = '';
  cards.innerHTML = '';
  setStatus('Idle');
});
