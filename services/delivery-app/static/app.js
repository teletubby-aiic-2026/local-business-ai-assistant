// 동네배달 — 시연용 가상 배달앱 화면. 빌드 없이 그대로 쓰는 파일입니다.
// 서버 주소는 index.html 의 <meta name="shop-api"> 한 곳에서 읽습니다 (기본 /api/shop).
(() => {
  'use strict';
  const API = document.querySelector('meta[name="shop-api"]')?.content || '/api/shop';
  const POLL_MS = 5000;
  const $ = (id) => document.getElementById(id);
  const screen = $('screen');

  // 어느 가게인가: /shop/?store=store_<가게>. 없으면 서버가 정한 시연 가게.
  const STORE = new URLSearchParams(location.search).get('store');
  const withStore = (path) => (STORE ? `${path}${path.includes('?') ? '&' : '?'}store=${encodeURIComponent(STORE)}` : path);

  const state = {
    view: 'store', tab: 'menu', store: null, reviews: null, online: true,
    cart: {}, cartOpen: false, orders: [], writing: null, form: { rating: 0, menu: null, text: '' },
  };

  // ── 도우미 ──
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const won = (n) => `${Number(n).toLocaleString('ko-KR')}원`;
  const pad = (n) => String(n).padStart(2, '0');
  const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? '' : `${d.getMonth() + 1}.${d.getDate()} ${pad(d.getHours())}:${pad(d.getMinutes())}`; };
  const stars = (n) => `<span class="s-stars" aria-label="별점 ${n || 0}점">${[1, 2, 3, 4, 5].map((i) => `<span class="${i <= (n || 0) ? 'on' : ''}">★</span>`).join('')}</span>`;
  const EMOJI = [['제육', '🍖'], ['불고기', '🥩'], ['된장', '🍲'], ['순두부', '🍲'], ['김치찌개', '🥘'], ['계란', '🥚'], ['국수', '🍜'], ['비빔', '🍚'], ['전', '🥞']];
  const emoji = (name) => (EMOJI.find(([k]) => name.includes(k)) || [0, '🍽️'])[1];
  let toastTimer;
  const toast = (msg) => { const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 2800); };

  async function api(path, options = {}) {
    const headers = { ...(options.body ? { 'Content-Type': 'application/json' } : {}) };
    const res = await fetch(API + withStore(path), { ...options, headers, credentials: 'same-origin' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.error?.message || '요청을 처리하지 못했어요.');
    return data;
  }

  // ── 데이터 ──
  async function loadStore() {
    try { state.store = await api('/store'); state.online = true; } catch (e) { state.online = false; state.storeError = e.message; }
    render();
  }
  async function loadReviews(quiet) {
    try {
      const data = await api('/reviews');
      const changed = JSON.stringify(data.items) !== JSON.stringify(state.reviews?.items);
      state.reviews = data; state.online = true;
      if (changed && !(quiet && isTyping())) render();
    } catch (e) {
      if (state.online) { state.online = false; if (!quiet) render(); }
    }
  }
  const isTyping = () => state.view === 'write';   // 리뷰를 쓰는 동안에는 화면을 다시 그리지 않습니다

  // ── 화면 ──
  const cartItems = () => (state.store?.menu || []).filter((m) => state.cart[m.name]).map((m) => ({ ...m, qty: state.cart[m.name] }));
  const cartCount = () => cartItems().reduce((s, i) => s + i.qty, 0);
  const cartTotal = () => cartItems().reduce((s, i) => s + i.qty * i.price, 0);

  function targetNote() {
    if (!state.online) return '<p class="s-target is-warn">리뷰 서버에 연결되지 않았어요. 리뷰 등록과 사장님 답글 확인이 잠시 안 돼요.</p>';
    return '<p class="s-target">여기서 쓴 리뷰는 이 가게의 리뷰로 쌓이고, 사장님 화면에 바로 전달돼요.</p>';
  }

  function storeView() {
    const s = state.store;
    if (!s) return `<p class="s-loading">${esc(state.storeError || '가게를 불러오고 있어요…')}</p>`;
    const r = state.reviews;
    const count = cartCount();
    const head = `
      <header class="s-top"><span class="shop__logo">🛵 동네배달</span>
        <button type="button" class="s-cartbtn" data-act="cart" aria-label="장바구니 ${count}개">🛍️${count ? `<b>${count}</b>` : ''}</button></header>
      <div class="s-hero" aria-hidden="true"><span>🍚</span><span>🍖</span><span>🍲</span></div>
      <section class="s-store">
        <h2>${esc(s.name)}</h2>
        <button type="button" class="s-rating" data-tab="reviews">★ <b>${r?.average ?? '-'}</b> 리뷰 ${r?.count ?? 0}개 ›</button>
        <ul class="s-meta">
          <li>오늘 ${esc(s.today?.hours || '-')}</li>
          ${s.min_order ? `<li>최소주문 ${won(s.min_order)}</li>` : ''}
          ${s.delivery_area ? `<li>배달 ${esc(s.delivery_area)}</li>` : ''}
        </ul>
      </section>
      ${(s.notices || []).map((n) => `<p class="s-notice">📢 ${esc(n)}</p>`).join('')}
      ${targetNote()}
      <nav class="s-tabs" role="tablist">
        ${[['menu', '메뉴'], ['reviews', `리뷰 ${r?.count ?? 0}`], ['info', '정보']].map(([id, label]) => `<button type="button" role="tab" aria-selected="${state.tab === id}" class="${state.tab === id ? 'is-active' : ''}" data-tab="${id}">${label}</button>`).join('')}
      </nav>`;
    let body = '';
    if (state.tab === 'menu') {
      body = `<ul class="s-menu">${s.menu.map((m) => `
        <li class="${m.sold_out ? 'is-soldout' : ''}">
          <div class="s-menu__text">
            <strong>${esc(m.name)} ${m.recommended ? '<em>추천</em>' : ''}</strong>
            ${m.ingredients.length ? `<p>${esc(m.ingredients.join(', '))}</p>` : ''}
            ${m.allergens.length ? `<small>알레르기 유발 재료: ${esc(m.allergens.join(', '))}</small>` : ''}
            <span>${won(m.price)}</span>
          </div>
          <div class="s-menu__side">
            <div class="s-thumb" aria-hidden="true">${emoji(m.name)}</div>
            ${m.sold_out ? '<small>오늘 품절</small>' : state.cart[m.name]
              ? `<div class="s-qty"><button type="button" data-qty="-1" data-name="${esc(m.name)}" aria-label="${esc(m.name)} 빼기">−</button><b>${state.cart[m.name]}</b><button type="button" data-qty="1" data-name="${esc(m.name)}" aria-label="${esc(m.name)} 더 담기">+</button></div>`
              : `<button type="button" class="s-add" data-qty="1" data-name="${esc(m.name)}">담기</button>`}
          </div>
        </li>`).join('')}</ul>${s.menu.length ? '' : '<p class="s-loading">아직 등록된 메뉴가 없어요. 사장님이 가게 정보에 메뉴를 넣으면 여기에 보여요.</p>'}`;
    } else if (state.tab === 'reviews') {
      const total = Object.values(r?.by_rating || {}).reduce((a, b) => a + b, 0);
      body = `<section class="s-reviews">
        <div class="s-score">
          <div><b>${r?.average ?? '-'}</b>${stars(Math.round(r?.average || 0))}</div>
          <ul>${[5, 4, 3, 2, 1].map((n) => { const c = r?.by_rating?.[n] || 0; return `<li><span>${n}점</span><i><u style="width:${total ? (c / total) * 100 : 0}%"></u></i><span>${c}</span></li>`; }).join('')}</ul>
        </div>
        <button type="button" class="s-write" data-act="write">✏️ 리뷰 쓰기</button>
        ${r ? (r.count ? '' : '<p class="s-loading">아직 리뷰가 없어요. 첫 리뷰를 남겨 보세요.</p>') : '<p class="s-loading">리뷰를 불러오고 있어요…</p>'}
        <ul class="s-rlist">${(r?.items || []).map((v) => `
          <li>
            <div class="s-rhead">
              <span class="s-avatar">${v.from_app ? '앱' : '손'}</span>
              <div><strong>${v.from_app ? '동네배달 손님' : '손님'}</strong><span>${esc(when(v.at))}</span></div>
              ${v.rating ? stars(v.rating) : ''}
            </div>
            <p>${esc(v.text)}</p>
            ${v.menu ? `<span class="s-chip">${esc(v.menu)}</span>` : ''}
            ${v.reply ? `<div class="s-reply"><strong>🏪 사장님</strong><p>${esc(v.reply.text)}</p></div>` : ''}
          </li>`).join('')}</ul>
      </section>`;
    } else {
      const days = [['mon', '월'], ['tue', '화'], ['wed', '수'], ['thu', '목'], ['fri', '금'], ['sat', '토'], ['sun', '일']];
      body = `<dl class="s-info">
        ${s.address ? `<div><dt>주소</dt><dd>${esc(s.address)}</dd></div>` : ''}
        <div><dt>영업시간</dt><dd>${days.map(([k, d]) => `${d} ${esc(s.hours?.[k] || '-')}`).join('<br>')}</dd></div>
        ${s.break_time ? `<div><dt>쉬는 시간</dt><dd>${esc(s.break_time)}</dd></div>` : ''}
        ${s.last_order ? `<div><dt>마지막 주문</dt><dd>${esc(s.last_order)}</dd></div>` : ''}
        ${s.holidays ? `<div><dt>휴무일</dt><dd>${esc(s.holidays)}</dd></div>` : ''}
        <div><dt>안내</dt><dd>시연용 가상 가게예요. 실제 주문·결제는 되지 않아요.</dd></div>
      </dl>`;
    }
    const bar = count && !state.cartOpen ? `<button type="button" class="s-cartbar" data-act="cart"><b>${count}</b> 장바구니 보기 <span>${won(cartTotal())}</span></button>` : '';
    return head + body + bar;
  }

  function ordersView() {
    return `<header class="s-top s-top--title"><h2>주문내역</h2></header>
      <ul class="s-orders">
        ${state.orders.length ? '' : '<li class="s-empty">아직 주문이 없어요. 가게에서 메뉴를 담아 주문해 보세요.</li>'}
        ${state.orders.map((o) => `
          <li>
            <div class="s-order__head"><strong>${esc(state.store?.name || '')}</strong><span>오늘 ${esc(o.at)} · 배달 완료 (시연)</span></div>
            <p>${o.items.map((i) => `${emoji(i.name)} ${esc(i.name)} ${i.qty}개`).join(', ')}</p>
            <div class="s-order__foot"><span>${won(o.total)}</span>
              ${o.reviewed ? '<em>리뷰 작성 완료</em>' : `<button type="button" class="s-add" data-act="write" data-order="${esc(o.id)}">리뷰 쓰기</button>`}</div>
          </li>`).join('')}
      </ul>`;
  }

  const QUICK = ['맛있게 잘 먹었어요. 양도 넉넉하고 반찬도 깔끔했어요!', '공깃밥이 빠진 채로 왔어요. 확인 부탁드려요.', '배달이 예상보다 30분 늦어서 음식이 식어 있었어요.', '덜 맵게도 주문할 수 있나요?'];
  function writeView() {
    const order = state.orders.find((o) => o.id === state.writing);
    const options = order ? order.items.map((i) => i.name) : (state.store?.menu || []).map((m) => m.name);
    const f = state.form;
    if (!options.includes(f.menu)) f.menu = options[0] || null;
    return `<header class="s-top s-top--title"><button type="button" class="s-back" data-act="back" aria-label="뒤로">←</button><h2>리뷰 쓰기</h2></header>
      <form class="s-form" id="review-form">
        <p class="s-form__q">음식은 어떠셨나요?</p>
        <span class="s-stars s-stars--pick">${[1, 2, 3, 4, 5].map((n) => `<button type="button" data-star="${n}" aria-label="${n}점" style="font-size:34px" class="${n <= f.rating ? 'on' : ''}">★</button>`).join('')}</span>
        <label>주문한 메뉴</label>
        <div class="s-chips">${options.map((n) => `<button type="button" data-menu="${esc(n)}" class="${f.menu === n ? 'is-active' : ''}">${esc(n)}</button>`).join('')}</div>
        <label for="review-text">리뷰 내용</label>
        <textarea id="review-text" rows="5" maxlength="1000" placeholder="음식 맛, 양, 포장, 배달은 어땠는지 적어 주세요. 연락처는 적지 마세요 (적으면 가려져요).">${esc(f.text)}</textarea>
        <div class="s-quick"><span>시연용 예시</span>${QUICK.map((q, i) => `<button type="button" data-quick="${i}">${esc(q.slice(0, 14))}…</button>`).join('')}</div>
        <button type="submit" class="s-order" id="review-submit" ${f.rating && f.text.trim().length >= 5 ? '' : 'disabled'}>${f.rating && f.text.trim().length >= 5 ? '리뷰 등록' : '별점과 내용(5자 이상)을 입력해 주세요'}</button>
      </form>`;
  }

  function sheetView() {
    if (!state.cartOpen) return '';
    const min = state.store?.min_order || 0;
    const total = cartTotal();
    return `<div class="s-sheet" role="dialog" aria-label="장바구니">
      <button type="button" class="s-sheet__dim" data-act="cart-close" aria-label="닫기"></button>
      <div class="s-sheet__body">
        <h3>장바구니</h3>
        <ul>${cartItems().map((i) => `<li><span>${emoji(i.name)} ${esc(i.name)}</span>
          <div class="s-qty"><button type="button" data-qty="-1" data-name="${esc(i.name)}" aria-label="빼기">−</button><b>${i.qty}</b><button type="button" data-qty="1" data-name="${esc(i.name)}" aria-label="더 담기">+</button></div>
          <span>${won(i.qty * i.price)}</span></li>`).join('')}</ul>
        <div class="s-sum s-sum--total"><span>주문 금액</span><span>${won(total)}</span></div>
        <button type="button" class="s-order" data-act="order" ${total < min || !total ? 'disabled' : ''}>${total < min ? `최소주문 ${won(min)}부터 주문할 수 있어요` : `${won(total)} 주문하기 (시연)`}</button>
      </div></div>`;
  }

  function render() {
    const keep = screen.scrollTop;
    screen.innerHTML = state.view === 'store' ? storeView() : state.view === 'orders' ? ordersView() : writeView();
    screen.scrollTop = keep;
    $('sheet').innerHTML = sheetView();
    $('nav').hidden = state.view === 'write';
    document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('is-active', b.dataset.view === state.view));
    $('orders-dot').hidden = !state.orders.some((o) => !o.reviewed);
  }

  // ── 동작 ──
  function setQty(name, d) {
    const qty = Math.max(0, (state.cart[name] || 0) + d);
    if (qty) state.cart[name] = qty; else delete state.cart[name];
    if (!cartCount()) state.cartOpen = false;
    render();
  }
  function order() {
    const now = new Date();
    state.orders.unshift({ id: `od_${now.getTime()}`, at: `${pad(now.getHours())}:${pad(now.getMinutes())}`, items: cartItems().map((i) => ({ name: i.name, qty: i.qty })), total: cartTotal(), reviewed: false });
    state.cart = {}; state.cartOpen = false; state.view = 'orders';
    render();
    toast('주문이 접수됐어요. (시연: 실제 주문·결제는 없어요)');
  }
  async function submitReview() {
    const f = state.form;
    const button = $('review-submit');
    button.disabled = true; button.textContent = '등록하는 중…';
    try {
      await api('/reviews', { method: 'POST', body: JSON.stringify({ text: f.text.trim(), rating: f.rating, menu: f.menu || undefined }) });
      const done = state.orders.find((o) => o.id === state.writing);
      if (done) done.reviewed = true;
      state.form = { rating: 0, menu: null, text: '' }; state.writing = null; state.view = 'store'; state.tab = 'reviews';
      await loadReviews();
      render();
      screen.scrollTop = 0;
      toast('리뷰를 등록했어요. 사장님께 전달됐어요.');
    } catch (e) {
      toast(e.message);
      button.disabled = false; button.textContent = '리뷰 등록';
    }
  }

  document.addEventListener('click', (e) => {
    const el = e.target.closest('button');
    if (!el) return;
    const d = el.dataset;
    if (d.view) { state.view = d.view; render(); }
    else if (d.tab) { state.tab = d.tab; render(); }
    else if (d.qty) setQty(d.name, Number(d.qty));
    else if (d.star) { state.form.rating = Number(d.star); render(); }
    else if (d.menu) { state.form.menu = d.menu; render(); }
    else if (d.quick) { state.form.text = QUICK[Number(d.quick)]; render(); }
    else if (d.act === 'cart') { if (cartCount()) { state.cartOpen = true; render(); } }
    else if (d.act === 'cart-close') { state.cartOpen = false; render(); }
    else if (d.act === 'order') order();
    else if (d.act === 'write') { state.writing = d.order || null; state.form = { rating: 0, menu: null, text: '' }; state.view = 'write'; render(); }
    else if (d.act === 'back') { state.view = state.writing ? 'orders' : 'store'; render(); }
  });
  document.addEventListener('input', (e) => {
    if (e.target.id !== 'review-text') return;
    state.form.text = e.target.value;
    const ok = state.form.rating && state.form.text.trim().length >= 5;
    const b = $('review-submit');
    b.disabled = !ok; b.textContent = ok ? '리뷰 등록' : '별점과 내용(5자 이상)을 입력해 주세요';
  });
  document.addEventListener('submit', (e) => { if (e.target.id === 'review-form') { e.preventDefault(); submitReview(); } });

  loadStore();
  loadReviews();
  setInterval(() => loadReviews(true), POLL_MS);
})();
