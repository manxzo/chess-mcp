import { Chessground } from 'https://cdn.jsdelivr.net/npm/chessground@9.2.1/+esm';

const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
const RATINGS = {
  brilliant: ['Brilliant', '!!'], great: ['Great', '!'], best: ['Best', '★'],
  excellent: ['Excellent', '✦'], good: ['Good', '✓'], book: ['Book', '≡'],
  inaccuracy: ['Inaccuracy', '?!'], mistake: ['Mistake', '?'], miss: ['Miss', '✕'], blunder: ['Blunder', '??'],
};
const REASONS = {
  checkmate: 'by checkmate', resigned: 'by resignation', draw_agreed: 'by agreement',
  stalemate: 'by stalemate', insufficient_material: '— insufficient material',
  threefold_repetition: '— repetition', fivefold_repetition: '— repetition',
  fifty_moves: '— 50-move rule', seventyfive_moves: '— 75-move rule',
};
const PRESETS = [['Beginner', 1320], ['Casual', 1500], ['Club', 1800], ['Strong', 2200], ['Expert', 2600], ['Master', 3000], ['Claude', null]];
const $ = (id) => document.getElementById(id);
const all = (selector) => [...document.querySelectorAll(selector)];
const phone = matchMedia('(max-width: 860px)');
const shortPhone = matchMedia('(max-width: 860px) and (min-width: 500px) and (max-height: 500px)');
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const other = (color) => color === 'white' ? 'black' : 'white';
const saved = {
  get(key) { try { return localStorage.getItem(key); } catch { return null; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch { /* Private browsing. */ } },
  del(key) { try { localStorage.removeItem(key); } catch { /* Private browsing. */ } },
};
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}
function button(text, action, cls) {
  const node = el('button', cls, text);
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
}
function svg(tag, attrs) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}
function text(id, value) {
  const node = $(id);
  if (node.textContent !== String(value)) node.textContent = value;
}
function tokenFromUrl() {
  const url = new URL(location.href);
  if (url.searchParams.has('token')) {
    saved.set('chess-token', url.searchParams.get('token'));
    url.searchParams.delete('token');
    history.replaceState(null, '', url.pathname + url.search + url.hash);
  }
  return saved.get('chess-token');
}
const app = {
  token: tokenFromUrl(), ws: null, retry: 0, lastSeq: -1, game: null, connected: false,
  flipped: false, showEval: saved.get('chess-eval') === '1', sound: saved.get('chess-sound') !== '0',
  confirmMoves: saved.get('chess-confirm') === '1', provisional: null,
  tab: 'moves', page: 'play', pageBackPending: false, unread: false, review: null, requestId: null, loading: null,
  pendingPly: null, pendingMove: null, games: null, boardKey: '', movesKey: '', bannerKey: '', chatKey: '',
  playersKey: '', modelsKey: '', settingsElo: undefined,
};
let reconnectTimer, pendingTimer, toastTimer;
const ground = Chessground($('board'), {
  fen: START_FEN, coordinates: true,
  animation: { enabled: !reduced.matches, duration: reduced.matches ? 0 : 160 },
  highlight: { lastMove: true, check: true },
  movable: { free: false, color: undefined, showDests: true, events: { after: onUserMove } },
  premovable: { enabled: !app.confirmMoves, showDests: true, events: {
    set() { text('status', 'Premove set'); },
    unset() { renderStatus(); },
  } },
  drawable: { enabled: true, visible: true },
});
reduced.addEventListener('change', () => ground.set({ animation: { enabled: !reduced.matches, duration: reduced.matches ? 0 : 160 } }));

// Keep the same input and scroll nodes alive across snapshots and breakpoints.
function placeForViewport() {
  const focus = document.activeElement;
  const chatScroll = $('chat').scrollTop, reportScroll = $('report').scrollTop;
  if ($('dlg-chat').open) $('dlg-chat').close();
  (phone.matches ? $('mobile-footer') : document.querySelector('.panel')).append($('game-footer'));
  (phone.matches ? $('chat-sheet-home') : $('chat-pane')).append($('chat-content'));
  (phone.matches ? $('mobile-report') : $('report-home')).append($('report'));
  if (phone.matches && app.page === 'review') setPage('review');
  $('chat').scrollTop = chatScroll;
  $('report').scrollTop = reportScroll;
  renderView();
  if (focus?.isConnected && focus.getClientRects().length) focus.focus({ preventScroll: true });
  requestAnimationFrame(() => { sizeBoard(); ground.redrawAll(); });
}
function sizeBoard() {
  if ($('app').hidden || $('board-column').hidden) return;
  const stack = $('board-stack');
  const rows = [...stack.children].filter((node) => node.id !== 'board-area' && node.getClientRects().length && (!shortPhone.matches || node.classList.contains('player')));
  const gap = parseFloat(getComputedStyle(stack).rowGap) || 0;
  const remaining = stack.clientHeight - rows.reduce((sum, node) => sum + node.getBoundingClientRect().height, 0) - gap * rows.length;
  const rail = app.showEval ? 16 : 0;
  const availableWidth = shortPhone.matches ? stack.clientWidth - 210 - gap : stack.clientWidth;
  const size = Math.max(0, Math.floor(Math.min(availableWidth - rail, remaining)));
  stack.style.setProperty('--board-size', size + 'px');
}
const layoutObserver = new ResizeObserver(sizeBoard);
layoutObserver.observe($('board-stack'));
for (const node of $('board-stack').children) if (node.id !== 'board-area') layoutObserver.observe(node);
layoutObserver.observe($('game-footer'));
new ResizeObserver(() => ground.redrawAll()).observe($('board-wrap'));
phone.addEventListener('change', placeForViewport);
shortPhone.addEventListener('change', () => requestAnimationFrame(sizeBoard));
function sizeSheets() {
  const viewport = window.visualViewport;
  const height = viewport?.height ?? innerHeight;
  const bottom = viewport ? Math.max(0, innerHeight - height - viewport.offsetTop) : 0;
  document.documentElement.style.setProperty('--visual-height', height + 'px');
  document.documentElement.style.setProperty('--keyboard-bottom', bottom + 'px');
}
window.visualViewport?.addEventListener('resize', sizeSheets);
window.visualViewport?.addEventListener('scroll', sizeSheets);
window.addEventListener('resize', sizeSheets);

// Native modal dialogs provide a focus trap, Escape handling and focus restoration.
function openDialog(id) {
  sizeSheets();
  if (!$(id).open) $(id).showModal();
}
all('[data-close]').forEach((node) => node.addEventListener('click', () => node.closest('dialog').close()));
all('dialog').forEach((dialog) => dialog.addEventListener('close', () => {
  if (dialog.contains($('toast'))) document.body.append($('toast'));
  renderView();
}));
function confirmBox(message, label) {
  text('confirm-text', message); text('confirm-ok', label);
  const dialog = $('dlg-confirm');
  dialog.returnValue = '';
  openDialog('dlg-confirm');
  return new Promise((resolve) => dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true }));
}
function showGate(message = 'Enter the password to play.') {
  all('dialog[open]').forEach((dialog) => dialog.close());
  $('app').hidden = true; $('gate').hidden = false;
  text('gate-msg', message);
  $('gate-input').focus();
}
function connect() {
  clearTimeout(reconnectTimer);
  if (!app.token) return showGate();
  $('gate').hidden = true; $('app').hidden = false;
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws?token=' + encodeURIComponent(app.token));
  app.ws = ws;
  app.connected = false;
  renderStatus();
  requestAnimationFrame(sizeBoard);
  ws.onopen = () => {
    if (app.ws !== ws) return;
    app.connected = true; app.retry = 0; app.lastSeq = -1;
    renderStatus();
    if (app.loading) send({ type: 'open_review', game_id: app.requestId });
    if ($('dlg-games').open || app.tab === 'review' || app.page === 'review') send({ type: 'list_games' });
  };
  ws.onmessage = (event) => {
    if (app.ws !== ws) return;
    try { handle(JSON.parse(event.data)); } catch (error) { console.error('Could not process chess update', error); toast('Could not read a game update.'); }
  };
  ws.onclose = (event) => {
    if (app.ws !== ws) return;
    app.ws = null; app.connected = false;
    clearPending();
    ground.cancelPremove();
    if (event.code === 4401) {
      saved.del('chess-token'); app.token = null;
      showGate('Wrong password. Try again.');
      return;
    }
    render();
    reconnectTimer = setTimeout(connect, Math.min(15000, 500 * 2 ** Math.min(app.retry++, 5)));
  };
}
function send(message) {
  if (app.ws?.readyState !== WebSocket.OPEN) { toast('Reconnecting… Please try again when connected.'); return false; }
  app.ws.send(JSON.stringify(message));
  return true;
}
$('gate-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const token = $('gate-input').value;
  if (!token) return;
  app.token = token; saved.set('chess-token', token); connect();
});
function handle(message) {
  if (message.type === 'state') {
    if (message.seq <= app.lastSeq) return;
    app.lastSeq = message.seq;
    const previous = app.game;
    app.game = message;
    if (previous?.game_id !== message.game_id) {
      clearPending(); ground.cancelPremove(); app.boardKey = '';
    }
    if (app.pendingMove && (message.fen !== app.pendingMove.fen || message.status !== 'active')) clearPending();
    if (app.provisional && (message.game_id !== app.provisional.gameId || message.fen !== app.provisional.fen || !canMove(app.provisional.uci))) clearPending();
    if (previous?.game_id === message.game_id) {
      if (message.moves.length > previous.moves.length) {
        const count = (fen) => (fen.split(' ')[0].match(/[prnbqk]/gi) || []).length;
        playSound(message.check ? 'check' : count(message.fen) < count(previous.fen) ? 'capture' : 'move');
      }
      if (previous.status === 'active' && message.status !== 'active') playSound('end');
    }
    if ($('dlg-promotion').open && (message.status !== 'active' || message.game_id !== promotion?.gameId || message.fen !== promotion?.fen)) $('dlg-promotion').close();
    const reviewVisible = phone.matches ? app.page === 'review' : app.tab === 'review';
    if (reviewVisible && !app.review && !app.loading && message.status !== 'active' && (previous?.status === 'active' || previous?.game_id !== message.game_id)) startReview(message.game_id);
    render();
  } else if (message.type === 'error') {
    clearPending(); app.boardKey = ''; render();
    if (app.loading && ['unknown_game', 'review_failed', 'no_engine', 'engine_failed'].includes(message.code)) {
      app.loading = null; app.requestId = null; renderReport();
      app.boardKey = ''; renderBoard(); renderStatus(); renderControls();
    }
    toast(message.message);
  } else if (message.type === 'games') {
    app.games = message.games; renderGames(); if (app.game) renderPlayers();
  } else if (message.type === 'review_progress' && message.game_id === app.requestId && app.loading) {
    app.loading = message; renderReport();
  } else if (message.type === 'review' && message.review.game_id === app.requestId) {
    app.loading = null;
    app.review = { data: message.review, ply: app.pendingPly ?? message.review.moves.length };
    app.review.ply = Math.max(0, Math.min(message.review.moves.length, app.review.ply));
    app.pendingPly = null; app.boardKey = ''; app.movesKey = '';
    buildReport(); render();
  }
}

function humanColor() {
  if (app.review) return ['Human', 'You'].includes(app.review.data.white.name) ? 'white' : 'black';
  return app.game?.human_color || 'white';
}
function orientation() { return app.flipped ? other(humanColor()) : humanColor(); }
function resultText(game) {
  return (game.winner == null ? 'Draw' : game.winner === game.human_color ? 'You won' : 'Claude won') + ' ' + (REASONS[game.status] || game.reason || game.result || '');
}
function claudeStatusText(claude) {
  if (!claude?.available) return "Claude isn't connected. Ask Claude to play chess in Claude Code.";
  switch (claude.status) {
    case 'starting': return 'Claude is starting…';
    case 'running': return 'Claude is connecting…';
    case 'stopping': return 'Claude is stopping…';
    case 'error': return 'Claude stopped: ' + (claude.error || 'Unknown error');
    default: return claude.auth?.logged_in ? "Claude isn't running." : 'Sign in to Claude to play.';
  }
}
function render() {
  if (!app.game) { renderView(); return; }
  renderBoard(); renderPlayers(); renderBanner(); renderStatus(); renderControls();
  renderMoves(); renderChat(); renderClaude(); renderEval(); renderReport(); renderView();
  requestAnimationFrame(sizeBoard);
}
function renderBoard() {
  const game = app.game, review = app.review;
  if (!game) return;
  if (app.provisional && !review && !app.loading) {
    ground.set({ fen: app.provisional.previewFen, orientation: orientation(),
      lastMove: [app.provisional.uci.slice(0, 2), app.provisional.uci.slice(2, 4)], check: false,
      movable: { color: undefined, dests: new Map() }, premovable: { enabled: false }, drawable: { autoShapes: [] } });
    return;
  }
  if (app.pendingMove && app.pendingMove.fen === game.fen && !review && !app.loading) {
    ground.set({ orientation: orientation() });
    return;
  }
  const move = review?.data.moves[review.ply - 1];
  const reviewing = Boolean(review || app.loading);
  const fen = review ? move?.fen || START_FEN : game.fen;
  const turn = review ? (fen.split(' ')[1] === 'w' ? 'white' : 'black') : game.turn;
  const key = JSON.stringify([game.game_id, fen, orientation(), reviewing, app.connected, game.status, reviewing ? null : game.dests, Boolean(app.pendingMove), move?.best_uci, move?.rating, turn, game.check, game.last_move, game.human_color, app.confirmMoves]);
  // Eval/chat/runner-only updates must never reset a drag, selection, or premove.
  if (key === app.boardKey) return;
  app.boardKey = key;
  const active = !reviewing && game.status === 'active' && app.connected && !app.pendingMove;
  const shapes = showBestMove(move)
    ? [{ orig: move.best_uci.slice(0, 2), dest: move.best_uci.slice(2, 4), brush: 'green' }] : [];
  ground.set({
    fen, orientation: orientation(), turnColor: turn,
    lastMove: review ? (move ? [move.uci.slice(0, 2), move.uci.slice(2, 4)] : undefined) : game.last_move || undefined,
    check: review ? Boolean(move && /[+#]$/.test(move.san)) : game.check,
    movable: { color: active ? game.human_color : undefined, dests: new Map(active ? Object.entries(game.dests || {}) : []) },
    premovable: { enabled: active && !app.confirmMoves },
    drawable: { autoShapes: shapes },
  });
  if (active && !app.confirmMoves && game.turn === game.human_color && ground.state.premovable.current) {
    const [from, to] = ground.state.premovable.current;
    const played = Boolean(game.dests?.[from]?.includes(to)) && ground.playPremove();
    if (!played) ground.cancelPremove();
  } else if (!active || app.confirmMoves) ground.cancelPremove();
}
function showBestMove(move) {
  return Boolean(move?.best_uci && move.best_uci !== move.uci && ['excellent', 'good', 'inaccuracy', 'mistake', 'miss', 'blunder'].includes(move.rating));
}
function renderPlayers() {
  const game = app.game;
  const reviewedGame = app.review && app.review.data.game_id !== game.game_id ? app.games?.find((item) => item.game_id === app.review.data.game_id) : game;
  const key = JSON.stringify([orientation(), humanColor(), game.claude_connected, reviewedGame?.game_id, reviewedGame?.elo, app.review?.data]);
  if (key === app.playersKey) return;
  app.playersKey = key;
  const player = (color) => {
    const human = color === humanColor();
    const row = el('div', 'player-info');
    row.append(el('span', 'avatar ' + (human ? 'human-avatar' : ''), human ? '●' : '♞'));
    const identity = el('div', 'identity');
    identity.append(el('strong', '', human ? 'You' : 'Claude'));
    const subtitle = human ? 'Playing ' + color : !reviewedGame ? 'Your opponent' : reviewedGame.elo == null ? 'Own game' : reviewedGame.elo + ' Elo';
    identity.append(el('span', 'player-subtitle', subtitle));
    row.append(identity);
    if (!human && !game.claude_connected && !app.review) row.append(el('span', 'offline', 'offline'));
    if (app.review) {
      const accuracy = app.review.data[color].accuracy;
      const acc = el('span', 'player-accuracy', accuracy == null ? '—' : accuracy.toFixed(1) + '%');
      acc.title = 'Accuracy'; row.append(acc);
    } else row.append(el('span', 'color-piece ' + color, color === 'white' ? '♔' : '♚'));
    return row;
  };
  $('player-top').replaceChildren(player(other(orientation())));
  $('player-bottom').replaceChildren(player(orientation()));
}
function renderStatus() {
  const game = app.game;
  let value = 'Connecting…';
  if (!app.connected) value = app.retry ? 'Reconnecting…' : 'Connecting…';
  else if (app.loading) value = 'Analysing the game…';
  else if (app.review) value = 'Reviewing your game';
  else if (game?.status !== 'active' && game) value = 'Game over · ' + game.result;
  else if (app.pendingMove) value = 'Sending move…';
  else if (game && !game.claude_connected && ['starting', 'running', 'stopping'].includes(game.claude?.status)) value = claudeStatusText(game.claude);
  else if (ground.state.premovable.current) value = 'Premove set';
  else if (game) value = game.turn === game.human_color ? 'Your move' : game.claude_connected ? 'Claude is thinking…' : 'Waiting for Claude';
  text('status', value); $('status').title = value;
  $('status').hidden = Boolean(app.provisional) || (!$('banner').hidden && $('banner').firstElementChild?.textContent === value);
  $('move-confirmation').hidden = !app.provisional;
}
function renderBanner() {
  const game = app.game, box = $('banner');
  const key = JSON.stringify([app.review != null, app.loading != null, game.game_id, game.status, game.result, game.winner, game.human_color, game.reason, game.draw_offer, game.claude_connected, game.claude?.status, game.claude?.error, game.claude?.auth?.logged_in, game.claude?.available]);
  if (key === app.bannerKey) return;
  app.bannerKey = key;
  const nodes = [];
  if (!app.review && !app.loading) {
    if (game.status === 'active' && game.draw_offer === 'claude') {
      nodes.push(el('span', '', 'Claude offers a draw'), button('Decline', () => send({ type: 'answer_draw', accept: false })), button('Accept', () => send({ type: 'answer_draw', accept: true }), 'primary'));
    } else if (game.status !== 'active') {
      nodes.push(el('span', '', resultText(game)), button('Review', () => startReview(app.game.game_id), 'primary'));
    } else if (!game.claude_connected && game.claude?.available && ['stopped', 'error'].includes(game.claude.status)) {
      const signedIn = game.claude.auth?.logged_in;
      nodes.push(el('span', '', claudeStatusText(game.claude)), button(signedIn ? 'Start Claude' : 'Sign in', () => {
        if (signedIn) send({ type: 'claude_start' });
        else { openDialog('dlg-more'); if (!app.game.claude.login?.busy) send({ type: 'claude_login' }); }
      }, 'primary'));
    } else if (!game.claude_connected && !game.claude?.available) {
      nodes.push(el('span', '', claudeStatusText(game.claude)));
    }
  }
  box.replaceChildren(...nodes); box.hidden = !nodes.length;
}
function renderControls() {
  const active = app.connected && app.game?.status === 'active' && !app.review && !app.loading;
  $('btn-draw').disabled = !active || app.game.draw_offer === 'human';
  $('btn-draw').title = app.game?.draw_offer === 'human' ? 'Draw offered' : 'Offer draw';
  $('btn-resign').disabled = !active;
  $('btn-new').disabled = !app.connected;
  all('[data-action="eval"]').forEach((node) => node.setAttribute('aria-pressed', String(app.showEval)));
  all('[data-action="sound"]').forEach((node) => node.setAttribute('aria-pressed', String(app.sound)));
  all('[data-action="confirm-moves"]').forEach((node) => node.setAttribute('aria-pressed', String(app.confirmMoves)));
}
function renderEval() {
  const move = app.review?.data.moves[app.review.ply - 1];
  const value = app.review ? move?.win_white_after ?? app.review.data.eval_series[0] ?? 50 : app.game?.eval?.win_white ?? 50;
  const label = app.review ? move?.eval_after || 'Starting position' : app.game?.eval?.text || 'Waiting for evaluation';
  $('evalbar').hidden = !app.showEval;
  $('evalbar').classList.toggle('flipped', orientation() === 'black');
  $('eval-fill').style.height = Math.max(0, Math.min(100, value)) + '%';
  $('evalbar').setAttribute('aria-label', 'Evaluation: ' + label + '. White win probability ' + Math.round(value) + '%');
  $('evalbar').title = label;
}
function badge(rating) {
  const entry = RATINGS[rating] || ['Unrated', '·'];
  const node = el('span', 'badge r-' + rating, entry[1]);
  node.title = entry[0]; node.setAttribute('aria-label', entry[0]); return node;
}
function moveLabel(move, ply) { return Math.ceil(ply / 2) + (ply % 2 ? '. ' : '… ') + move.san; }
function moveCell(move, ply, strip = false) {
  const canReview = Boolean(app.review) || app.game?.status !== 'active';
  const node = canReview ? button(strip ? moveLabel(move, ply) : move.san, () => {
    if (app.review) goTo(ply);
    else startReview(app.game.game_id, ply);
  }, 'mv') : el('span', 'mv', strip ? moveLabel(move, ply) : move.san);
  node.dataset.ply = ply;
  node.setAttribute('aria-label', moveLabel(move, ply) + (move.rating ? ', ' + (RATINGS[move.rating]?.[0] || move.rating) : ''));
  if (move.rating) node.append(badge(move.rating));
  return node;
}
function fillMoves(list, moves) {
  const rows = [];
  for (let index = 0; index < moves.length; index += 2) {
    const row = el('li');
    row.append(el('span', 'move-number', index / 2 + 1 + '.'), moveCell(moves[index], index + 1));
    if (moves[index + 1]) row.append(moveCell(moves[index + 1], index + 2));
    rows.push(row);
  }
  list.replaceChildren(...rows);
}
function revealCurrent(container, horizontal = false) {
  const current = container.querySelector('[aria-current="step"]');
  if (!current || !container.clientHeight) return;
  const a = current.getBoundingClientRect(), b = container.getBoundingClientRect();
  if (horizontal) {
    if (a.left < b.left) container.scrollLeft += a.left - b.left;
    else if (a.right > b.right) container.scrollLeft += a.right - b.right;
  } else {
    if (a.top < b.top) container.scrollTop += a.top - b.top;
    else if (a.bottom > b.bottom) container.scrollTop += a.bottom - b.bottom;
  }
}
function highlightMoves() {
  const ply = app.review ? app.review.ply : app.game?.moves.length;
  all('[data-ply]').forEach((node) => {
    const selected = Number(node.dataset.ply) === ply;
    node.classList.toggle('current', selected);
    if (selected) node.setAttribute('aria-current', 'step'); else node.removeAttribute('aria-current');
  });
}
function renderMoves() {
  const moves = app.review ? app.review.data.moves : app.game.moves;
  const key = JSON.stringify([app.review?.data.game_id || app.game.game_id, app.game.status, Boolean(app.review), moves]);
  if (key !== app.movesKey) {
    const scroll = $('moves').scrollTop;
    const following = $('moves').scrollHeight - scroll - $('moves').clientHeight < 60;
    fillMoves($('moves'), moves);
    $('move-strip').replaceChildren(...moves.map((move, index) => moveCell(move, index + 1, true)));
    if (!moves.length) $('move-strip').append(el('span', 'muted strip-empty', 'Make the first move'));
    $('moves-empty').hidden = moves.length > 0;
    highlightMoves();
    if (following) requestAnimationFrame(() => revealCurrent($('moves')));
    else $('moves').scrollTop = scroll;
    requestAnimationFrame(() => revealCurrent($('move-strip'), true));
    app.movesKey = key;
  } else highlightMoves();
}
function chatVisible() { return phone.matches ? $('dlg-chat').open : app.tab === 'chat'; }
function setUnread(value) {
  app.unread = value;
  all('.unread-dot').forEach((node) => { node.hidden = !value; });
  $('nav-chat').setAttribute('aria-label', value ? 'Chat, unread message from Claude' : 'Chat');
  $('tab-chat').setAttribute('aria-label', value ? 'Chat, unread message from Claude' : 'Chat');
}
let chatGame = null, chatIds = [], chatMessages = [], chatFollowing = true;
$('chat').addEventListener('scroll', () => {
  if (chatVisible()) chatFollowing = $('chat').scrollHeight - $('chat').scrollTop - $('chat').clientHeight < 64;
}, { passive: true });
function followChat() {
  if (chatFollowing) requestAnimationFrame(() => { $('chat').scrollTop = $('chat').scrollHeight; });
}
function renderChat() {
  const messages = app.game.chat || [];
  const key = JSON.stringify([app.game.game_id, messages]);
  if (key === app.chatKey) return;
  const box = $('chat'), sameGame = chatGame === app.game.game_id;
  const nearBottom = chatVisible() ? box.scrollHeight - box.scrollTop - box.clientHeight < 64 : chatFollowing;
  const oldScroll = box.scrollTop;
  const appendOnly = sameGame && messages.length >= chatMessages.length && chatMessages.every((message, index) => message === JSON.stringify(messages[index]));
  const fresh = sameGame ? messages.filter((message) => !chatIds.includes(message.id)) : [];
  if (!appendOnly) box.replaceChildren();
  for (const message of appendOnly ? messages.slice(chatIds.length) : messages) {
    const bubble = el('p', 'bubble ' + (message.sender === 'human' ? 'human' : 'claude'));
    bubble.append(el('span', 'bubble-name', message.sender === 'human' ? 'You' : 'Claude'), el('span', '', message.text));
    box.append(bubble);
  }
  if (!sameGame) setUnread(false);
  if (fresh.some((message) => message.sender === 'claude')) {
    if (!chatVisible()) setUnread(true);
    playSound('chat');
  }
  chatGame = app.game.game_id; chatIds = messages.map((message) => message.id); app.chatKey = key;
  chatMessages = messages.map((message) => JSON.stringify(message));
  if (nearBottom || !sameGame || fresh.at(-1)?.sender === 'human') {
    chatFollowing = true;
    if (chatVisible()) followChat();
  }
  else box.scrollTop = oldScroll;
}
$('chat-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const input = $('chat-input'), value = input.value.trim();
  if (value && send({ type: 'chat', text: value })) input.value = '';
});
$('chat-input').addEventListener('keydown', (event) => { if (event.isComposing && event.key === 'Enter') event.preventDefault(); });

function renderClaude() {
  const claude = app.game?.claude;
  const difficulty = app.game?.difficulty;
  const elo = difficulty?.elo ?? null;
  if (elo !== app.settingsElo && !$('settings-difficulty').contains(document.activeElement)) {
    settingsDifficulty.set(elo); app.settingsElo = elo;
  }
  for (const id of ['settings-difficulty-slider', 'new-difficulty-slider']) {
    $(id).min = String(difficulty?.min ?? 1320);
    $(id).max = String(difficulty?.max ?? 3190);
  }
  $('claude-unavailable').hidden = Boolean(claude?.available);
  $('claude-controls').hidden = !claude?.available;
  if (!claude?.available) return;
  const signedIn = Boolean(claude.auth?.logged_in), login = claude.login || {};
  text('account-status', signedIn ? 'Signed in' + (claude.auth.email ? ' as ' + claude.auth.email : '') : 'Connect your Claude account to play.');
  $('account-actions').hidden = Boolean(login.busy);
  $('claude-login').hidden = signedIn; $('claude-logout').hidden = !signedIn;
  $('login-flow').hidden = !login.busy;
  let loginUrl = null;
  try { const url = new URL(login.url); if (['https:', 'http:'].includes(url.protocol)) loginUrl = url.href; } catch { /* Link not ready. */ }
  $('login-link').hidden = !loginUrl; $('login-preparing').hidden = Boolean(loginUrl);
  if (loginUrl) $('login-link').href = loginUrl;
  $('login-checking').hidden = !login.verifying;
  $('code-continue').disabled = Boolean(login.verifying);
  // Keep code editable and preserve selection, even while server status changes.
  const modelsKey = JSON.stringify(claude.models || []);
  if (modelsKey !== app.modelsKey) {
    $('claude-model').replaceChildren(...(claude.models || []).map((model) => {
      const option = el('option', '', model.name); option.value = model.id; return option;
    }));
    app.modelsKey = modelsKey;
  }
  if (document.activeElement !== $('claude-model')) $('claude-model').value = claude.model;
  text('runner-status', ({ stopped: 'Stopped', starting: 'Starting…', running: 'Running', stopping: 'Stopping…', error: 'Error' })[claude.status] || 'Stopped');
  text('runner-error', claude.error || ''); $('runner-error').hidden = !claude.error;
  const canStop = ['starting', 'running', 'stopping'].includes(claude.status);
  text('claude-control', canStop ? 'Stop Claude' : 'Start Claude');
  $('claude-control').disabled = claude.status === 'stopping' || (!canStop && !signedIn);
}
for (const [id, type] of [['claude-login', 'claude_login'], ['claude-logout', 'claude_logout'], ['claude-cancel', 'claude_login_cancel']]) {
  $(id).addEventListener('click', () => send({ type }));
}
$('claude-control').addEventListener('click', () => send({ type: ['starting', 'running', 'stopping'].includes(app.game?.claude?.status) ? 'claude_stop' : 'claude_start' }));
$('claude-model').addEventListener('change', (event) => send({ type: 'claude_model', model: event.target.value }));
$('code-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const code = $('claude-code').value.trim();
  if (code && !app.game?.claude?.login?.verifying) send({ type: 'claude_login_code', code });
});
function difficultyControl(id, onChange) {
  const box = $(id), presets = el('div', 'presets'), output = el('output', 'difficulty-value');
  let elo = 1500;
  const slider = el('input');
  slider.type = 'range'; slider.min = '1320'; slider.max = '3190'; slider.step = '10'; slider.value = '1500';
  slider.id = id + '-slider';
  slider.setAttribute('aria-label', 'Target difficulty rating');
  const label = el('label', '', 'Target rating'); label.htmlFor = slider.id;
  const entries = PRESETS.map(([name, value]) => {
    const node = button(name, () => { set(value); onChange?.(value); });
    node.append(el('small', '', value == null ? 'Own game' : String(value)));
    node.setAttribute('aria-pressed', 'false'); presets.append(node); return [node, value];
  });
  function set(value) {
    elo = value;
    output.textContent = value == null ? 'Claude plays its own game' : String(value);
    if (value != null) slider.value = value;
    slider.setAttribute('aria-valuetext', value == null ? 'Claude — move the slider to set a target rating' : String(value));
    for (const [node, target] of entries) node.setAttribute('aria-pressed', String(target === value));
  }
  slider.addEventListener('input', () => set(Number(slider.value)));
  slider.addEventListener('change', () => onChange?.(elo));
  box.append(presets, label, output, slider);
  set(1500);
  return { set, get: () => elo };
}
const newDifficulty = difficultyControl('new-difficulty');
const settingsDifficulty = difficultyControl('settings-difficulty', (elo) => {
  if (send({ type: 'set_difficulty', elo })) { app.settingsElo = elo; toast('Difficulty requested for the next game.'); }
});
$('start-game').addEventListener('click', async () => {
  const selectedGame = app.game?.game_id;
  const color = document.querySelector('input[name="side"]:checked').value;
  const elo = newDifficulty.get();
  if (app.game?.status === 'active' && app.game.moves.length >= 2) {
    if (!await confirmBox('Resign this game and start a new one?', 'Resign & play')) return;
    if (app.game?.game_id !== selectedGame) { toast('The game changed. Please try again.'); return; }
    if (app.game.status === 'active' && !send({ type: 'resign' })) return;
  }
  if (send({ type: 'new_game', human_color: color, elo })) { $('dlg-new').close(); closeReview(); }
});

// Only authoritative snapshots acknowledge moves; don't replay them after reconnecting.
function clearPending() {
  app.pendingMove = null; app.provisional = null; app.boardKey = ''; clearTimeout(pendingTimer);
}
function canMove(uci) {
  const game = app.game;
  return Boolean(app.connected && game?.status === 'active' && !app.review && !app.loading &&
    game.turn === game.human_color && game.dests?.[uci.slice(0, 2)]?.includes(uci.slice(2, 4)));
}
function prepareMove(uci) {
  if (!canMove(uci)) { cancelMove(); return; }
  const from = uci.slice(0, 2), to = uci.slice(2, 4), piece = ground.state.pieces.get(to);
  // Chessground moves the piece and castling rook; complete promotion/en passant locally.
  const changes = new Map();
  if (piece?.role === 'pawn' && from[0] !== to[0] && app.game.fen.split(' ')[3] === to) changes.set(to[0] + from[1], undefined);
  if (uci[4]) changes.set(to, { role: ({ q: 'queen', r: 'rook', b: 'bishop', n: 'knight' })[uci[4]], color: app.game.human_color });
  if (changes.size) ground.setPieces(changes);
  if (!app.confirmMoves) { submitMove(uci); return; }
  ground.cancelPremove();
  app.provisional = { uci, gameId: app.game.game_id, fen: app.game.fen, previewFen: ground.getFen() };
  renderBoard(); renderStatus(); requestAnimationFrame(sizeBoard);
}
function confirmMove() {
  const move = app.provisional;
  if (!move) return;
  if (move.gameId !== app.game?.game_id || move.fen !== app.game.fen || !canMove(move.uci)) { cancelMove(); return; }
  app.provisional = null;
  submitMove(move.uci);
}
function cancelMove() {
  app.provisional = null; app.boardKey = '';
  renderBoard(); renderStatus(); requestAnimationFrame(sizeBoard);
}
function submitMove(uci) {
  if (app.pendingMove || !canMove(uci) || !send({ type: 'move', move: uci })) { cancelMove(); return; }
  app.pendingMove = { fen: app.game.fen };
  ground.set({ movable: { color: undefined }, premovable: { enabled: false } });
  renderStatus(); requestAnimationFrame(sizeBoard);
  pendingTimer = setTimeout(() => { clearPending(); renderBoard(); renderStatus(); }, 5000);
}
let promotion = null;
function onUserMove(from, to) {
  if (app.pendingMove || app.provisional || !canMove(from + to)) {
    app.boardKey = ''; renderBoard(); return;
  }
  const piece = ground.state.pieces.get(to);
  if (piece?.role === 'pawn' && ['1', '8'].includes(to[1])) {
    promotion = { from, to, gameId: app.game.game_id, fen: app.game.fen };
    const white = app.game.human_color === 'white';
    $('promotion-choices').replaceChildren(...[['q', 'Queen', white ? '♕' : '♛'], ['r', 'Rook', white ? '♖' : '♜'], ['b', 'Bishop', white ? '♗' : '♝'], ['n', 'Knight', white ? '♘' : '♞']].map(([suffix, name, glyph]) => {
      const node = button(glyph, () => { promotion = null; prepareMove(from + to + suffix); $('dlg-promotion').close(); });
      node.setAttribute('aria-label', 'Promote to ' + name); return node;
    }));
    openDialog('dlg-promotion');
  } else prepareMove(from + to);
}
$('dlg-promotion').addEventListener('close', () => {
  if (promotion) { promotion = null; app.boardKey = ''; renderBoard(); }
  $('board').focus({ preventScroll: true });
});

function selectTab(tab) {
  app.tab = tab;
  if (tab === 'review') showReview();
  if (tab === 'chat') setUnread(false);
  renderView();
  if (tab === 'chat') followChat();
}
function selectPage(page) {
  if (page === 'chat') {
    openDialog('dlg-chat'); setUnread(false);
    renderView();
    followChat();
    return;
  }
  if (page === 'more') { openDialog('dlg-more'); renderView(); return; }
  setPage(page);
  if (page === 'review') showReview();
  renderView();
  requestAnimationFrame(() => { sizeBoard(); ground.redrawAll(); });
}
function setPage(page, navigate = true) {
  if (navigate && phone.matches && !app.pageBackPending) {
    if (page === 'review' && history.state?.chessPage !== 'review') history.pushState({ ...history.state, chessPage: 'review' }, '');
    else if (page === 'play' && history.state?.chessPage === 'review') {
      app.pageBackPending = true;
      history.back();
    }
  }
  app.page = page;
}
window.addEventListener('popstate', () => {
  // A quick Play → Review tap can happen before the requested Back completes.
  if (app.pageBackPending) {
    app.pageBackPending = false;
    if (phone.matches && app.page === 'review') history.pushState({ ...history.state, chessPage: 'review' }, '');
    return;
  }
  if (history.state?.chessPage === 'review' && phone.matches) {
    setPage('review', false); showReview(); renderView();
  } else if (app.page === 'review') closeReview(false);
});
function renderView() {
  $('board-column').hidden = phone.matches && app.page === 'review';
  $('mobile-report').hidden = !phone.matches || app.page !== 'review';
  $('moves-pane').hidden = app.tab !== 'moves';
  $('chat-pane').hidden = app.tab !== 'chat';
  $('report').hidden = phone.matches ? app.page !== 'review' : app.tab !== 'review';
  $('report-home').hidden = phone.matches || app.tab !== 'review';
  all('[data-tab]').forEach((node) => {
    node.setAttribute('aria-selected', String(node.dataset.tab === app.tab));
    node.tabIndex = node.dataset.tab === app.tab ? 0 : -1;
  });
  const activePage = $('dlg-chat').open ? 'chat' : $('dlg-more').open ? 'more' : app.page;
  all('[data-page]').forEach((node) => {
    if (node.dataset.page === activePage) node.setAttribute('aria-current', 'page'); else node.removeAttribute('aria-current');
  });
}
all('[data-tab]').forEach((node) => node.addEventListener('click', () => selectTab(node.dataset.tab)));
all('[data-page]').forEach((node) => node.addEventListener('click', () => selectPage(node.dataset.page)));
document.querySelector('.panel-tabs').addEventListener('keydown', (event) => {
  const tabs = all('[data-tab]'), index = tabs.indexOf(document.activeElement);
  if (index < 0 || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault(); event.stopPropagation();
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next].focus(); selectTab(tabs[next].dataset.tab);
});
const actions = {
  more: () => openDialog('dlg-more'),
  new: () => { newDifficulty.set(app.game?.difficulty?.elo ?? null); openDialog('dlg-new'); },
  draw: () => send({ type: 'offer_draw' }),
  resign: async () => {
    const gameId = app.game?.game_id;
    if (await confirmBox('Resign this game?', 'Resign') && app.game?.game_id === gameId && app.game.status === 'active') send({ type: 'resign' });
  },
  flip: () => { app.flipped = !app.flipped; render(); },
  eval: () => { app.showEval = !app.showEval; saved.set('chess-eval', app.showEval ? '1' : '0'); render(); },
  sound: () => { app.sound = !app.sound; saved.set('chess-sound', app.sound ? '1' : '0'); renderControls(); if (app.sound) playSound('move'); },
  'confirm-moves': () => {
    app.confirmMoves = !app.confirmMoves; saved.set('chess-confirm', app.confirmMoves ? '1' : '0');
    ground.cancelPremove(); cancelMove(); renderControls();
  },
  'confirm-move': confirmMove,
  'cancel-move': cancelMove,
  'review-current': () => startReview(app.game.game_id),
  games: () => { openDialog('dlg-games'); requestGames(); },
  'close-review': closeReview,
  'view-board': () => selectPage('play'),
};
all('[data-action]').forEach((node) => node.addEventListener('click', () => actions[node.dataset.action]()));
function requestGames() {
  if (!app.games) {
    for (const id of ['games-list', 'review-games']) $(id).replaceChildren(el('li', 'empty', 'Loading past games…'));
  }
  send({ type: 'list_games' });
}
function renderGames() {
  for (const id of ['games-list', 'review-games']) {
    const list = $(id), scroll = list.scrollTop;
    list.replaceChildren(...(app.games || []).map((game) => {
      const outcome = game.winner == null ? 'Draw' : game.winner === game.human_color ? 'Won' : 'Lost';
      const date = new Date((game.ended_at || game.started_at) * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
      const row = button('', () => { all('dialog[open]').forEach((dialog) => dialog.close()); startReview(game.game_id); }, 'game-row');
      const detail = el('span', 'game-description');
      detail.append(el('strong', '', game.opening || Math.ceil(game.moves / 2) + ' moves'), el('small', '', (game.elo == null ? 'Claude' : game.elo) + ' · ' + date));
      row.append(el('span', 'outcome ' + outcome.toLowerCase(), outcome), detail, el('span', 'muted', game.reviewed ? '✓' : '›'));
      row.setAttribute('aria-label', 'Review game: ' + outcome + ', ' + detail.textContent);
      const item = el('li'); item.append(row); return item;
    }));
    if (!app.games?.length) list.append(el('li', 'empty', 'No finished games yet.'));
    list.scrollTop = scroll;
  }
}
function showReview() {
  if (!app.review && !app.loading && app.game?.status !== 'active' && app.game) startReview(app.game.game_id);
  else if (!app.review && !app.loading) requestGames();
  renderReport();
}
function startReview(gameId, ply = null) {
  if (!send({ type: 'open_review', game_id: gameId })) return;
  ground.cancelPremove(); clearPending();
  app.review = null; app.requestId = gameId; app.pendingPly = ply;
  app.loading = { game_id: gameId, done: 0, total: 0 };
  app.tab = 'review'; setPage('review'); app.boardKey = '';
  $('report').scrollTop = 0;
  render();
}
function closeReview(navigate = true) {
  app.review = null; app.requestId = null; app.loading = null; app.pendingPly = null;
  app.tab = 'moves'; setPage('play', navigate); app.boardKey = ''; app.movesKey = '';
  render();
}
function buildReport() {
  const { data } = app.review;
  const human = data[humanColor()], claude = data[other(humanColor())];
  $('accuracy').replaceChildren(...[[human, 'You'], [claude, 'Claude']].map(([side, name]) => {
    const card = el('div', 'accuracy-card'), ring = el('div', 'accuracy-ring');
    ring.style.setProperty('--accuracy', Math.max(0, Math.min(100, side.accuracy ?? 0)) + '%');
    ring.append(el('strong', '', side.accuracy == null ? '—' : side.accuracy.toFixed(1)));
    card.append(ring, el('strong', '', name), el('span', 'muted', 'Accuracy')); return card;
  }));
  const head = el('thead'), heading = el('tr');
  for (const label of ['You', 'Move rating', 'Claude']) { const cell = el('th', '', label); cell.scope = 'col'; heading.append(cell); }
  head.append(heading);
  const body = el('tbody');
  for (const [rating, [name]] of Object.entries(RATINGS)) {
    const row = el('tr'), label = el('th'); label.scope = 'row';
    label.append(badge(rating), el('span', '', name));
    row.append(el('td', '', human.counts?.[rating] || 0), label, el('td', '', claude.counts?.[rating] || 0)); body.append(row);
  }
  $('counts').replaceChildren(el('caption', '', 'Move ratings'), head, body);
  fillMoves($('review-moves'), data.moves);
  renderGraph();
}
function renderReport() {
  const finished = app.game && app.game.status !== 'active';
  text('review-empty-text', finished ? 'Your game is ready to review.' : 'Finish a game to review it.');
  $('review-current').hidden = !finished;
  $('review-current').disabled = !app.connected;
  $('review-empty').hidden = Boolean(app.review || app.loading);
  $('review-progress').hidden = !app.loading;
  $('report-data').hidden = !app.review;
  $('board-review').hidden = !app.review;
  text('review-opening', app.review?.data.opening || (app.review ? 'Every move is a chance to learn.' : 'Learn from every game.'));
  if (app.loading) {
    const { done, total } = app.loading;
    $('progress').value = total ? done / total * 100 : 0;
    text('progress-text', total ? 'Analysing position ' + done + ' of ' + total + '…' : 'Starting analysis…');
  }
  if (!app.review) return;
  const { data, ply } = app.review;
  all('.review-position').forEach((node) => { node.textContent = ply + ' / ' + data.moves.length; });
  all('[data-step]').forEach((node) => { node.disabled = ['first', 'prev'].includes(node.dataset.step) ? ply === 0 : ply === data.moves.length; });
}
function renderGraph() {
  const { data, ply } = app.review, n = Math.max(1, data.eval_series.length - 1);
  const x = (index) => index / n * 400, y = (value) => 100 - Math.max(0, Math.min(100, value ?? 50)) * .9;
  const points = data.eval_series.map((value, index) => x(index) + ',' + y(value));
  const nodes = [
    svg('rect', { x: 0, y: 0, width: 400, height: 55, class: 'graph-white' }),
    svg('rect', { x: 0, y: 55, width: 400, height: 55, class: 'graph-black' }),
    svg('path', { d: 'M0,55 L' + points.join(' L') + ' L400,55 Z', class: 'graph-area' }),
    svg('path', { d: 'M' + points.join(' L'), class: 'graph-line' }),
    svg('line', { x1: 0, x2: 400, y1: 55, y2: 55, class: 'graph-mid' }),
  ];
  for (const move of data.moves) {
    if (!['brilliant', 'great', 'inaccuracy', 'mistake', 'miss', 'blunder'].includes(move.rating)) continue;
    const group = svg('g', { class: 'graph-mark r-' + move.rating });
    group.append(svg('circle', { cx: x(move.ply), cy: y(move.win_white_after), r: 6 }));
    const glyph = svg('text', { x: x(move.ply), y: y(move.win_white_after) + 2.5, 'text-anchor': 'middle' });
    glyph.textContent = RATINGS[move.rating][1]; group.append(glyph);
    const title = svg('title', {}); title.textContent = moveLabel(move, move.ply) + ' — ' + RATINGS[move.rating][0]; group.append(title); nodes.push(group);
  }
  nodes.push(svg('line', { id: 'graph-cursor', x1: x(ply), x2: x(ply), y1: 0, y2: 110, class: 'graph-cursor' }));
  $('graph').replaceChildren(...nodes);
  $('graph').setAttribute('aria-valuemax', data.moves.length);
  updateReviewPosition();
}
function updateReviewPosition() {
  if (!app.review) return;
  const { data, ply } = app.review, move = data.moves[ply - 1];
  const x = ply / Math.max(1, data.eval_series.length - 1) * 400;
  $('graph-cursor')?.setAttribute('x1', x); $('graph-cursor')?.setAttribute('x2', x);
  $('graph').setAttribute('aria-valuenow', ply); $('graph').setAttribute('aria-valuetext', 'Position ' + ply + ' of ' + data.moves.length);
  const detail = $('move-detail');
  if (move) {
    const line = el('div', 'move-verdict');
    line.append(badge(move.rating), el('strong', '', moveLabel(move, ply)), el('span', '', RATINGS[move.rating]?.[0] || 'Unrated'), el('strong', 'move-eval', move.eval_after));
    detail.replaceChildren(line);
    if (move.best_line && showBestMove(move)) detail.append(el('p', 'best-line', 'Best line: ' + move.best_line));
    text('board-review-label', moveLabel(move, ply) + ' · ' + (RATINGS[move.rating]?.[0] || 'Unrated') + ' · ' + move.eval_after);
  } else {
    detail.replaceChildren(el('p', 'muted', 'Starting position. Step through the game to find your turning points.'));
    text('board-review-label', 'Starting position');
  }
  highlightMoves();
}
function goTo(ply) {
  if (!app.review) return;
  app.review.ply = Math.max(0, Math.min(app.review.data.moves.length, ply));
  renderBoard(); renderEval(); renderReport(); updateReviewPosition();
  revealCurrent($('moves')); revealCurrent($('move-strip'), true);
}
all('[data-step]').forEach((node) => node.addEventListener('click', () => {
  if (!app.review) return;
  const { ply, data } = app.review;
  goTo(({ first: 0, prev: ply - 1, next: ply + 1, last: data.moves.length })[node.dataset.step]);
}));
$('graph').addEventListener('click', (event) => {
  if (!app.review) return;
  const rect = $('graph').getBoundingClientRect();
  goTo(Math.round((event.clientX - rect.left) / rect.width * app.review.data.moves.length));
});
document.addEventListener('keydown', (event) => {
  if (event.isComposing || event.target.closest('input, textarea, select, [contenteditable="true"]') || document.querySelector('dialog[open]')) return;
  if (app.provisional && ['Enter', 'Escape'].includes(event.key)) {
    event.preventDefault();
    if (event.key === 'Enter') confirmMove(); else cancelMove();
    return;
  }
  if (event.key === 'Escape' && (app.review || app.loading || app.page === 'review' || app.tab === 'review')) {
    event.preventDefault(); closeReview(); return;
  }
  if (!app.review) return;
  const { ply, data } = app.review;
  const target = ({ ArrowLeft: ply - 1, ArrowRight: ply + 1, Home: 0, End: data.moves.length })[event.key];
  if (target != null) { event.preventDefault(); goTo(target); }
});
let touch = null;
$('board').addEventListener('touchstart', (event) => {
  touch = event.touches.length === 1 ? [event.touches[0].clientX, event.touches[0].clientY] : null;
}, { passive: true });
$('board').addEventListener('touchend', (event) => {
  if (!app.review || !touch) return;
  const dx = event.changedTouches[0].clientX - touch[0], dy = event.changedTouches[0].clientY - touch[1]; touch = null;
  if (Math.abs(dx) > 35 && Math.abs(dx) > Math.abs(dy)) goTo(app.review.ply + (dx < 0 ? 1 : -1));
}, { passive: true });
$('board').addEventListener('touchcancel', () => { touch = null; }, { passive: true });

let audioContext = null, interacted = false;
function unlockAudio() {
  interacted = true;
  if (!app.sound) return;
  try {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!audioContext && Context) audioContext = new Context();
    audioContext?.resume().catch(() => {});
  } catch { /* Audio is optional. */ }
}
document.addEventListener('pointerdown', unlockAudio, { passive: true });
document.addEventListener('keydown', unlockAudio);
function playSound(kind) {
  if (!interacted || !app.sound || !audioContext || audioContext.state !== 'running') return;
  const notes = {
    move: [[460, 0, .07]], capture: [[250, 0, .065], [175, .04, .08]],
    check: [[660, 0, .07], [880, .08, .09]],
    end: [[523, 0, .10], [659, .09, .10], [784, .18, .14]],
    chat: [[740, 0, .055], [988, .06, .07]],
  }[kind] || [];
  for (const [frequency, delay, duration] of notes) {
    const oscillator = audioContext.createOscillator(), gain = audioContext.createGain();
    const start = audioContext.currentTime + delay;
    oscillator.type = kind === 'capture' ? 'triangle' : 'sine';
    oscillator.frequency.setValueAtTime(frequency, start);
    gain.gain.setValueAtTime(0, start); gain.gain.linearRampToValueAtTime(.055, start + .008); gain.gain.exponentialRampToValueAtTime(.001, start + duration);
    oscillator.connect(gain); gain.connect(audioContext.destination);
    oscillator.start(start); oscillator.stop(start + duration + .01);
    oscillator.onended = () => { oscillator.disconnect(); gain.disconnect(); };
  }
}
function toast(message) {
  const dialog = all('dialog[open]').at(-1);
  (dialog || document.body).append($('toast'));
  text('toast', message); $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4000);
}
sizeSheets(); placeForViewport(); renderControls(); connect();
