import { Chessground } from 'https://cdn.jsdelivr.net/npm/chessground@9.2.1/+esm';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const RATINGS = {
  brilliant: ['Brilliant', '!!'],
  great: ['Great', '!'],
  best: ['Best', '★'],
  excellent: ['Excellent', '✦'],
  good: ['Good', '✓'],
  book: ['Book', '≡'],
  inaccuracy: ['Inaccuracy', '?!'],
  mistake: ['Mistake', '?'],
  miss: ['Miss', '✕'],
  blunder: ['Blunder', '??'],
};
const KEY_RATINGS = new Set(['brilliant', 'great', 'miss', 'mistake', 'blunder']);
const NO_ARROW = new Set(['book', 'best', 'brilliant', 'great']);
const REASONS = {
  checkmate: 'by checkmate',
  resigned: 'by resignation',
  draw_agreed: 'by agreement',
  stalemate: 'by stalemate',
  insufficient_material: '· insufficient material',
  threefold_repetition: '· repetition',
  fivefold_repetition: '· repetition',
  fifty_moves: '· 50-move rule',
  seventyfive_moves: '· 75-move rule',
};
const SVG_NS = 'http://www.w3.org/2000/svg';

const $ = (id) => document.getElementById(id);
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}
function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}
function button(text, onClick, cls) {
  const b = el('button', cls, text);
  b.type = 'button';
  b.title = text;
  b.setAttribute('aria-label', text);
  b.addEventListener('click', onClick);
  return b;
}
const saved = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  del: (k) => { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } },
};

function tokenFromUrl() {
  const url = new URL(location.href);
  const token = url.searchParams.get('token');
  if (token) {
    saved.set('chess-token', token);
    url.searchParams.delete('token');
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }
  return saved.get('chess-token');
}

const app = {
  token: tokenFromUrl(),
  ws: null,
  retry: 0,
  game: null,
  flipped: false,
  showEval: saved.get('chess-eval') === '1',
  review: null, // { data, ply }
  loading: null, // { game_id, done, total }
  chatKey: '',
};

const ground = Chessground($('board'), {
  coordinates: true,
  animation: { duration: matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 160 },
  highlight: { lastMove: true, check: true },
  movable: { free: false, showDests: true, events: { after: onUserMove } },
  premovable: { enabled: false },
  drawable: { enabled: true, visible: true },
});

// ---------------- connection ----------------
function connect() {
  if (!app.token) return showGate();
  hideGate();
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(app.token)}`);
  app.ws = ws;
  ws.onopen = () => { app.retry = 0; };
  ws.onmessage = (event) => handle(JSON.parse(event.data));
  ws.onclose = (event) => {
    if (app.ws !== ws) return;
    app.ws = null;
    if (event.code === 4401) {
      saved.del('chess-token');
      app.token = null;
      showGate('That access link is not valid any more. Ask Claude for a new one.');
      return;
    }
    renderStatus();
    setTimeout(connect, Math.min(10000, 500 * 2 ** app.retry++));
  };
}

function send(msg) {
  if (app.ws && app.ws.readyState === WebSocket.OPEN) app.ws.send(JSON.stringify(msg));
  else toast('Reconnecting…');
}

function handle(msg) {
  if (msg.type === 'state') {
    app.game = msg;
    render();
  } else if (msg.type === 'error') {
    toast(msg.message);
    if (app.loading && !app.review) closeReview();
    else render();
  } else if (msg.type === 'games') {
    renderGames(msg.games);
  } else if (msg.type === 'review_progress') {
    if (app.loading && app.loading.game_id === msg.game_id) {
      app.loading = msg;
      renderReview();
    }
  } else if (msg.type === 'review') {
    openReview(msg.review);
  }
}

// ---------------- gate ----------------
function showGate(message) {
  $('app').hidden = true;
  $('gate').hidden = false;
  if (message) $('gate-msg').textContent = message;
  $('gate-input').focus();
}

function hideGate() {
  $('gate').hidden = true;
  $('app').hidden = false;
  requestAnimationFrame(() => ground.redrawAll());
}

$('gate-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const raw = $('gate-input').value.trim();
  if (!raw) return;
  let token = raw;
  try { token = new URL(raw).searchParams.get('token') || raw; } catch { /* not a URL: use as the token */ }
  saved.set('chess-token', token);
  app.token = token;
  connect();
});

// ---------------- rendering ----------------
const humanColor = () => (app.game ? app.game.human_color : 'white');
const other = (color) => (color === 'white' ? 'black' : 'white');
const orientation = () => (app.flipped ? other(humanColor()) : humanColor());

function render() {
  if (!app.game) return;
  if (app.review) renderReviewBoard();
  else renderLiveBoard();
  renderPlayers();
  renderStatus();
  renderBanner();
  renderControls();
  renderMoves();
  renderChat();
  renderEval();
}

function renderLiveBoard() {
  const g = app.game;
  const myTurn = g.status === 'active' && g.turn === g.human_color;
  ground.set({
    fen: g.fen,
    orientation: orientation(),
    turnColor: g.turn,
    lastMove: g.last_move,
    check: g.check,
    movable: { color: myTurn ? g.human_color : undefined, dests: new Map(Object.entries(g.dests || {})) },
    drawable: { autoShapes: [] },
  });
}

function renderPlayers() {
  const g = app.game;
  const label = (color) => {
    const isHuman = color === g.human_color;
    const row = el('div', 'player-name');
    row.append(el('span', `dot ${color}`), el('span', null, isHuman ? 'You' : 'Claude'));
    if (!isHuman && !g.claude_connected && !app.review) row.append(el('span', 'presence', 'offline'));
    if (app.review) {
      const acc = app.review.data[color].accuracy;
      if (acc != null) row.append(el('span', 'acc', acc.toFixed(1)));
    }
    return row;
  };
  $('player-bottom').replaceChildren(label(orientation()));
  $('player-top').replaceChildren(label(other(orientation())));
}

function resultText(g) {
  const who = g.winner == null ? 'Draw' : g.winner === g.human_color ? 'You won' : 'Claude won';
  return `${who} ${REASONS[g.status] || ''}`.trim();
}

function renderStatus() {
  const g = app.game;
  const status = $('status');
  if (!g) return;
  if (!app.ws) status.textContent = 'Reconnecting…';
  else if (app.review) status.textContent = app.review.data.opening || 'Unnamed opening';
  else if (app.loading) status.textContent = 'Analysing the game…';
  else if (g.status !== 'active') status.textContent = 'Game over';
  else if (!g.claude_connected) status.textContent = 'Claude isn’t connected. Ask Claude to play chess in Claude Code.';
  else status.textContent = g.turn === g.human_color ? 'Your move' : 'Claude is thinking…';
}

function renderBanner() {
  const g = app.game;
  const banner = $('banner');
  banner.replaceChildren();
  if (!app.review && !app.loading) {
    if (g.status === 'active' && g.draw_offer === 'claude') {
      banner.append(
        el('span', null, 'Claude offers a draw'),
        button('Decline', () => send({ type: 'answer_draw', accept: false })),
        button('Accept', () => send({ type: 'answer_draw', accept: true }), 'primary'),
      );
    } else if (g.status !== 'active') {
      banner.append(el('span', null, resultText(g)));
      if (g.moves.length) banner.append(button('Review', () => startReview(g.game_id), 'primary'));
    }
  }
  banner.hidden = banner.childElementCount === 0;
}

function renderControls() {
  const g = app.game;
  const active = g.status === 'active' && !app.review && !app.loading;
  $('btn-resign').disabled = !active;
  $('btn-draw').disabled = !active || g.draw_offer === 'human';
  $('btn-draw').title = g.draw_offer === 'human' ? 'Draw offered' : 'Offer a draw';
  $('btn-eval').setAttribute('aria-pressed', String(app.showEval));
}

function badge(rating) {
  const [label, glyph] = RATINGS[rating];
  const b = el('span', `badge r-${rating}`, glyph);
  b.title = label;
  b.setAttribute('aria-label', label);
  return b;
}

function moveCell(move, ply) {
  if (!app.review) return el('span', 'mv', move.san);
  const cell = button(move.san, () => goTo(ply), 'mv');
  cell.append(badge(move.rating));
  cell.setAttribute('aria-label', `Move ${Math.ceil(ply / 2)}, ${ply % 2 ? 'White' : 'Black'}: ${move.san}, ${RATINGS[move.rating][0]}`);
  if (ply === app.review.ply) {
    cell.classList.add('current');
    cell.setAttribute('aria-current', 'step');
  }
  return cell;
}

function renderMoves() {
  const list = $('moves');
  const moves = app.review ? app.review.data.moves : app.loading ? [] : app.game.moves;
  const rows = [];
  for (let i = 0; i < moves.length; i += 2) {
    const li = el('li');
    li.append(el('span', 'no', `${i / 2 + 1}.`), moveCell(moves[i], i + 1));
    if (moves[i + 1]) li.append(moveCell(moves[i + 1], i + 2));
    rows.push(li);
  }
  list.replaceChildren(...rows);
  const current = list.querySelector('.current');
  if (current) {
    // Scroll only the move list; keep the board in place on narrow screens.
    const row = current.parentElement;
    const offset = row.getBoundingClientRect().top - list.getBoundingClientRect().top;
    if (offset < 0) list.scrollTop += offset;
    else if (offset + row.offsetHeight > list.clientHeight) list.scrollTop += offset + row.offsetHeight - list.clientHeight;
  }
  else list.scrollTop = list.scrollHeight;
}

function renderChat() {
  const chat = app.game.chat;
  const key = `${app.game.game_id}:${chat.length}`;
  if (key === app.chatKey) return;
  const box = $('chat');
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.replaceChildren(...chat.map((m) => el('p', `msg ${m.sender}`, m.text)));
  const last = chat[chat.length - 1];
  if (nearBottom || !app.chatKey || (last && last.sender === 'human')) box.scrollTop = box.scrollHeight;
  app.chatKey = key;
}

function renderEval() {
  const bar = $('evalbar');
  let ev = null;
  if (app.review) {
    const m = app.review.data.moves[app.review.ply - 1];
    ev = m ? { win_white: m.win_white_after, text: m.eval_after } : { win_white: app.review.data.eval_series[0], text: '' };
  } else if (app.game.status === 'active' && !app.loading) {
    ev = app.game.eval;
  }
  bar.hidden = !app.showEval || !ev;
  if (bar.hidden) return;
  bar.classList.toggle('flipped', orientation() === 'black');
  bar.querySelector('.evalbar-fill').style.height = `${ev.win_white}%`;
  bar.title = ev.text ? `Evaluation ${ev.text}` : 'Evaluation';
}

// ---------------- moving ----------------
function onUserMove(orig, dest) {
  const piece = ground.state.pieces.get(dest);
  if (piece && piece.role === 'pawn' && (dest[1] === '8' || dest[1] === '1')) {
    askPromotion(orig, dest, app.game.human_color);
    return;
  }
  send({ type: 'move', move: orig + dest });
}

function askPromotion(orig, dest, color) {
  const box = $('promo');
  const glyphs = color === 'white' ? { q: '♕', r: '♖', b: '♗', n: '♘' } : { q: '♛', r: '♜', b: '♝', n: '♞' };
  const choose = (piece) => {
    box.hidden = true;
    $('board').focus({ preventScroll: true });
    send({ type: 'move', move: orig + dest + piece });
  };
  box.replaceChildren(
    ...Object.entries(glyphs).map(([piece, glyph]) => {
      const choice = button(glyph, () => choose(piece));
      const name = { q: 'Queen', r: 'Rook', b: 'Bishop', n: 'Knight' }[piece];
      choice.title = name;
      choice.setAttribute('aria-label', `Promote to ${name.toLowerCase()}`);
      return choice;
    }),
    button('×', () => { box.hidden = true; render(); $('board').focus({ preventScroll: true }); }),
  );
  box.lastElementChild.title = 'Cancel promotion';
  box.lastElementChild.setAttribute('aria-label', 'Cancel promotion');
  box.hidden = false;
  box.querySelector('button').focus();
}

// Keep keyboard focus in the board's promotion picker until a choice is made.
$('promo').addEventListener('keydown', (event) => {
  const choices = [...event.currentTarget.querySelectorAll('button')];
  if (event.key === 'Escape') {
    event.preventDefault();
    choices.at(-1).click();
  } else if (event.key === 'Tab') {
    event.preventDefault();
    const next = choices.indexOf(document.activeElement) + (event.shiftKey ? -1 : 1);
    choices[(next + choices.length) % choices.length].focus();
  }
});

// ---------------- controls ----------------
function confirmBox(text, okLabel) {
  const dlg = $('dlg-confirm');
  $('confirm-text').textContent = text;
  $('confirm-ok').textContent = okLabel;
  $('confirm-ok').setAttribute('aria-label', okLabel);
  dlg.returnValue = '';
  dlg.showModal();
  return new Promise((resolve) => dlg.addEventListener('close', () => resolve(dlg.returnValue === 'ok'), { once: true }));
}

$('btn-new').addEventListener('click', async () => {
  const g = app.game;
  if (!g) return;
  if (g.status === 'active' && g.moves.length >= 2) {
    if (!(await confirmBox('Resign this game and start a new one?', 'Resign'))) return;
    send({ type: 'resign' });
  }
  const dlg = $('dlg-new');
  dlg.returnValue = '';
  dlg.showModal();
  dlg.addEventListener('close', () => {
    if (['white', 'black', 'random'].includes(dlg.returnValue)) {
      closeReview();
      send({ type: 'new_game', human_color: dlg.returnValue });
    }
  }, { once: true });
});
$('btn-resign').addEventListener('click', async () => {
  if (await confirmBox('Resign this game?', 'Resign')) send({ type: 'resign' });
});
$('btn-draw').addEventListener('click', () => send({ type: 'offer_draw' }));
$('btn-flip').addEventListener('click', () => { app.flipped = !app.flipped; render(); });
$('btn-eval').addEventListener('click', () => {
  app.showEval = !app.showEval;
  saved.set('chess-eval', app.showEval ? '1' : '0');
  render();
});
$('btn-games').addEventListener('click', () => {
  $('games-list').replaceChildren(el('li', 'muted', 'Loading…'));
  $('dlg-games').returnValue = '';
  $('dlg-games').showModal();
  send({ type: 'list_games' });
});
$('dlg-games').addEventListener('close', () => {
  const id = $('dlg-games').returnValue;
  if (id && id !== 'close') startReview(id);
});
$('chat-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const input = $('chat-input');
  const text = input.value.trim();
  if (!text) return;
  send({ type: 'chat', text });
  input.value = '';
});

function renderGames(games) {
  const list = $('games-list');
  if (!games.length) {
    list.replaceChildren(el('li', 'muted', 'No finished games yet.'));
    return;
  }
  list.replaceChildren(...games.map((g) => {
    const outcome = g.winner == null ? 'Draw' : g.winner === g.human_color ? 'Won' : 'Lost';
    const when = new Date((g.ended_at || g.started_at) * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    const row = el('button', 'game-row');
    row.value = g.game_id;
    row.title = `${outcome}: ${g.opening || `${g.moves} moves`} — ${when}`;
    row.setAttribute('aria-label', `Review game. ${row.title}`);
    row.append(el('span', `outcome ${outcome.toLowerCase()}`, outcome), el('span', 'opening', g.opening || `${g.moves} moves`), el('span', 'date', when));
    const li = el('li');
    li.append(row);
    return li;
  }));
}

// ---------------- review ----------------
function startReview(gameId) {
  app.review = null;
  app.loading = { game_id: gameId, done: 0, total: 0 };
  document.body.classList.add('reviewing');
  send({ type: 'open_review', game_id: gameId });
  render();
  renderReview();
}

function openReview(data) {
  app.loading = null;
  app.review = { data, ply: data.moves.length };
  document.body.classList.add('reviewing');
  render();
  renderReview();
}

function closeReview() {
  app.review = null;
  app.loading = null;
  document.body.classList.remove('reviewing');
  render();
  renderReview();
}
$('btn-close-review').addEventListener('click', closeReview);
$('review-first').addEventListener('click', () => goTo(0));
$('review-prev').addEventListener('click', () => goTo(app.review.ply - 1));
$('review-next').addEventListener('click', () => goTo(app.review.ply + 1));
$('review-last').addEventListener('click', () => goTo(app.review.data.moves.length));

function goTo(ply) {
  if (!app.review) return;
  app.review.ply = Math.max(0, Math.min(app.review.data.moves.length, ply));
  render();
  renderReview();
}

function renderReviewBoard() {
  const { data, ply } = app.review;
  const m = data.moves[ply - 1];
  const shapes = [];
  if (m && m.best_uci && m.best_uci !== m.uci && !NO_ARROW.has(m.rating)) {
    shapes.push({ orig: m.best_uci.slice(0, 2), dest: m.best_uci.slice(2, 4), brush: 'green' });
  }
  const fen = m ? m.fen : START_FEN;
  ground.set({
    fen,
    orientation: orientation(),
    turnColor: fen.split(' ')[1] === 'w' ? 'white' : 'black',
    lastMove: m ? [m.uci.slice(0, 2), m.uci.slice(2, 4)] : null,
    check: Boolean(m && /[+#]$/.test(m.san)),
    movable: { color: undefined, dests: new Map() },
    drawable: { autoShapes: shapes },
  });
}

function renderReview() {
  const on = Boolean(app.review || app.loading);
  $('review').hidden = !on;
  $('btn-close-review').hidden = !on;
  $('panel-title').textContent = on ? 'Game review' : 'Claude';
  $('best-line').hidden = !app.review;
  $('review-nav').hidden = !app.review;
  if (app.review) {
    const { ply, data } = app.review;
    $('review-position').textContent = `${ply} / ${data.moves.length}`;
    for (const id of ['review-first', 'review-prev']) $(id).disabled = ply === 0;
    for (const id of ['review-next', 'review-last']) $(id).disabled = ply === data.moves.length;
  }
  const progress = $('review-progress');
  progress.hidden = !app.loading;
  if (app.loading) {
    const { done, total } = app.loading;
    progress.querySelector('span').style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
    progress.querySelector('p').textContent = total ? `Analysing position ${done} of ${total}…` : 'Starting analysis…';
  }
  for (const id of ['accuracy', 'graph', 'counts']) $(id).hidden = !app.review;
  if (!app.review) return;
  const { data, ply } = app.review;
  renderAccuracy(data);
  renderCounts(data);
  renderGraph(data, ply);
  renderBestLine(data, ply);
}

function sides(data) {
  const human = data.white.name === 'You' ? data.white : data.black;
  return [human, human === data.white ? data.black : data.white];
}

function renderAccuracy(data) {
  const card = (p) => {
    const c = el('div', 'acc-card');
    c.append(el('span', 'acc-name', p.name), el('strong', null, p.accuracy == null ? '–' : p.accuracy.toFixed(1)), el('span', 'acc-label', 'accuracy'));
    return c;
  };
  $('accuracy').replaceChildren(...sides(data).map(card));
}

function renderCounts(data) {
  const [human, claude] = sides(data);
  const rows = Object.keys(RATINGS)
    .filter((r) => human.counts[r] || claude.counts[r])
    .map((r) => {
      const tr = el('tr');
      const name = el('th');
      name.append(badge(r), el('span', null, RATINGS[r][0]));
      tr.append(el('td', 'n', String(human.counts[r] || 0)), name, el('td', 'n', String(claude.counts[r] || 0)));
      return tr;
    });
  $('counts').replaceChildren(...rows);
}

function renderGraph(data, ply) {
  const W = 300;
  const H = 60;
  const n = data.eval_series.length - 1;
  const x = (i) => (n ? (i / n) * W : 0);
  const y = (w) => H - (w / 100) * H;
  const points = data.eval_series.map((w, i) => `${x(i).toFixed(1)},${y(w).toFixed(1)}`);
  const nodes = [
    svg('path', { d: `M0,${H} L${points.join(' L')} L${W},${H} Z`, class: 'g-white' }),
    svg('line', { x1: 0, x2: W, y1: H / 2, y2: H / 2, class: 'g-mid' }),
    svg('line', { x1: x(ply), x2: x(ply), y1: 0, y2: H, class: 'g-cursor' }),
  ];
  for (const m of data.moves) {
    if (!KEY_RATINGS.has(m.rating)) continue;
    const cx = x(m.ply);
    const cy = y(m.win_white_after);
    nodes.push(svg('line', { x1: cx, x2: cx, y1: cy, y2: cy, class: `g-dot r-${m.rating}` }));
  }
  $('graph').replaceChildren(...nodes);
  $('graph').setAttribute('aria-valuemax', String(n));
  $('graph').setAttribute('aria-valuenow', String(ply));
  $('graph').setAttribute('aria-valuetext', `Position ${ply} of ${n}`);
}

$('graph').addEventListener('click', (event) => {
  if (!app.review) return;
  const rect = event.currentTarget.getBoundingClientRect();
  goTo(Math.round(((event.clientX - rect.left) / rect.width) * app.review.data.moves.length));
});

function renderBestLine(data, ply) {
  const box = $('best-line');
  const m = data.moves[ply - 1];
  if (!m) {
    box.replaceChildren(el('span', 'muted', 'Start position. Use ← → to step through the game.'));
    return;
  }
  const label = `${Math.ceil(m.ply / 2)}${m.color === 'white' ? '.' : '…'} ${m.san}`;
  const parts = [badge(m.rating), el('strong', null, label), el('span', null, RATINGS[m.rating][0]), el('span', 'eval', m.eval_after)];
  if (m.best_line && m.best_uci !== m.uci && !NO_ARROW.has(m.rating)) parts.push(el('span', 'best', `Best: ${m.best_line}`));
  box.replaceChildren(...parts);
}

document.addEventListener('keydown', (event) => {
  if (!app.review || event.target.closest('input, textarea, dialog')) return;
  if (event.key === 'ArrowLeft') goTo(app.review.ply - 1);
  else if (event.key === 'ArrowRight') goTo(app.review.ply + 1);
  else if (event.key === 'Home') goTo(0);
  else if (event.key === 'End') goTo(app.review.data.moves.length);
  else if (event.key === 'Escape') closeReview();
  else return;
  event.preventDefault();
});

let touchX = null;
$('board').addEventListener('touchstart', (event) => { touchX = event.touches[0].clientX; }, { passive: true });
$('board').addEventListener('touchend', (event) => {
  if (!app.review || touchX == null) return;
  const dx = event.changedTouches[0].clientX - touchX;
  touchX = null;
  if (Math.abs(dx) > 40) goTo(app.review.ply + (dx < 0 ? 1 : -1));
});

// ---------------- toast ----------------
let toastTimer;
function toast(text) {
  const t = $('toast');
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3500);
}

connect();
