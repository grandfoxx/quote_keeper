(function () {
  console.log('[Quote-Keeper-Plugin] Category-Level Fullpage UI loaded.');

  const PLUGIN_ID = 'quote_keeper';
  let currentType = 'general';
  let allQuotes = [];
  let editingId = null;
  let searchDebounceTimer = null;

  function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
  }

  function callAction(actionId, context) {
    return fetch('/api/media/context-menu/book/plugins/action', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        plugin_id: PLUGIN_ID,
        action_id: actionId,
        type: currentType,
        context: context || {},
      }),
    }).then((res) => res.json());
  }

  function formatDateTime(unixSeconds) {
    if (!unixSeconds) return '';
    const d = new Date(unixSeconds * 1000);
    return d.toLocaleString('ko-KR', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  // ── 타입 전환 ──
  document.querySelectorAll('.qk-type-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.qk-type-btn').forEach((b) => b.classList.remove('active'));
      const target = e.currentTarget;
      target.classList.add('active');
      currentType = target.dataset.type || 'general';
      loadQuotes();
      loadStats();
    });
  });

  // ── 검색 ──
  const searchInput = document.getElementById('qk-search');
  searchInput.addEventListener('input', () => {
    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(loadQuotes, 250);
  });

  document.getElementById('qk-refresh').addEventListener('click', () => {
    loadQuotes();
    loadStats();
  });

  // ── 목록 로드/렌더 ──
  function loadQuotes() {
    const query = searchInput.value.trim();
    callAction('list_quotes', { query }).then((data) => {
      if (!data.success) {
        console.warn('[Quote-Keeper-Plugin] list_quotes failed', data.error);
        return;
      }
      allQuotes = data.items || [];
      renderList();
    });
  }

  function renderList() {
    const listEl = document.getElementById('qk-list');
    const emptyEl = document.getElementById('qk-empty');
    listEl.querySelectorAll('.qk-card').forEach((el) => el.remove());

    if (allQuotes.length === 0) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;

    const frag = document.createDocumentFragment();
    allQuotes.forEach((q) => {
      const card = document.createElement('div');
      card.className = 'qk-card';

      // book_title이 "시리즈명#58"처럼 series_name을 그대로 접두어로 포함하는 경우가
      // 많아서, 그럴 땐 겹치는 부분을 잘라낸다. 다만 "#58" 같은 접미어는 실제 권/화가
      // 아니라 내부 카탈로그 번호인 경우가 많으므로, "권"/"화" 글자가 들어있어 진짜
      // 권차수로 보일 때만 남기고 그 외에는 버린다.
      let volumePart = q.book_title || '';
      if (q.series_name && volumePart.startsWith(q.series_name)) {
        volumePart = volumePart.slice(q.series_name.length).trim();
      }
      if (!/[권화]/.test(volumePart)) {
        volumePart = '';
      }

      // 페이지 번호는 리더 화면(폰트/화면 크기)에 따라 매번 달라지고 하이라이트를
      // 만들 당시 값이 저장되지도 않아서, 시간이 지나면 예전 글귀의 페이지 표시가
      // 어긋난다. 챕터는 폰트/화면 크기와 무관하게 고정되므로 그걸 기준으로 표시한다.
      const chapterLabel = (q.format === 'epub' && q.chapter_idx !== null && q.chapter_idx !== undefined)
        ? `${q.chapter_idx + 1}장`
        : '';
      const volumeLabel = [volumePart, chapterLabel].filter(Boolean).join(' ');

      const heading = q.series_name && q.series_name !== q.book_title
        ? (volumeLabel
            ? `${escapeHtml(q.series_name)} <span class="qk-muted">(${escapeHtml(volumeLabel)})</span>`
            : escapeHtml(q.series_name))
        : (chapterLabel ? `${escapeHtml(q.book_title)} <span class="qk-muted">(${escapeHtml(chapterLabel)})</span>` : escapeHtml(q.book_title));

      card.innerHTML = `
        <div class="qk-card-header">
          <div class="qk-card-book">
            ${q.cover_image ? `<img src="${escapeHtml(q.cover_image)}" class="qk-cover" alt="cover">` : '<div class="qk-cover qk-cover-empty"><i class="fa-solid fa-book"></i></div>'}
            <div>
              <div class="qk-book-title">${heading}</div>
              <div class="qk-meta-row">
                <span class="qk-badge qk-badge-muted"><i class="fa-regular fa-clock"></i> ${formatDateTime(q.created_at)}</span>
              </div>
            </div>
          </div>
          <div class="qk-card-actions">
            <button type="button" class="qk-icon-btn qk-edit-note" title="메모 수정"><i class="fa-solid fa-pen"></i></button>
            <button type="button" class="qk-icon-btn qk-delete" title="삭제"><i class="fa-solid fa-trash"></i></button>
          </div>
        </div>
        <blockquote class="qk-quote">${escapeHtml(q.quote)}</blockquote>
        ${q.note ? `<div class="qk-note"><i class="fa-solid fa-note-sticky"></i> ${escapeHtml(q.note)}</div>` : ''}
      `;

      card.querySelector('.qk-edit-note').addEventListener('click', () => openNoteModal(q));
      card.querySelector('.qk-delete').addEventListener('click', () => deleteQuote(q.id));

      frag.appendChild(card);
    });
    listEl.appendChild(frag);
  }

  // ── 통계 ──
  function loadStats() {
    callAction('get_stats', {}).then((data) => {
      if (!data.success) return;
      const s = data.stats || {};
      document.getElementById('qk-stat-total').textContent = s.total ?? 0;
      document.getElementById('qk-stat-books').textContent = s.books ?? 0;
      document.getElementById('qk-stat-recent').textContent = s.recent_30d ?? 0;
    });
  }

  // ── 메모 수정 모달 ──
  const modal = document.getElementById('qk-note-modal');
  const noteInput = document.getElementById('qk-note-input');

  function openNoteModal(quote) {
    editingId = quote.id;
    noteInput.value = quote.note || '';
    modal.hidden = false;
    noteInput.focus();
  }

  function closeNoteModal() {
    modal.hidden = true;
    editingId = null;
  }

  document.getElementById('qk-note-cancel').addEventListener('click', closeNoteModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) closeNoteModal();
  });

  document.getElementById('qk-note-save').addEventListener('click', () => {
    if (!editingId) return;
    callAction('update_note', { id: editingId, note: noteInput.value }).then((data) => {
      if (data.success) {
        closeNoteModal();
        loadQuotes();
      } else {
        alert(data.error || '저장에 실패했습니다.');
      }
    });
  });

  // ── 삭제 ──
  function deleteQuote(id) {
    if (!confirm('이 글귀를 삭제할까요? 책에 표시된 하이라이트(형광펜)도 함께 지워집니다.')) return;
    callAction('delete_quote', { id }).then((data) => {
      if (data.success) {
        loadQuotes();
        loadStats();
      } else {
        alert(data.error || '삭제에 실패했습니다.');
      }
    });
  }

  // ── 초기 로드 ──
  loadQuotes();
  loadStats();
})();
