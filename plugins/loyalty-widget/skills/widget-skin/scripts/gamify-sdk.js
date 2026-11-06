(function () {
  'use strict';

  var cfg = window.__GAMIFY__ || {};
  var live = Object.assign({}, cfg.live || {});
  var route = parseRoute(location.pathname);
  var hosts = cfg.hosts || (live.apiUrl ? [{ apiUrl: live.apiUrl, cdnUrl: cfg.cdnUrl }] : []);
  var mode = route && hosts.length ? 'live' : mode;
  var cdnUrl = cfg.cdnUrl || '';

  function parseRoute(pathname) {
    var parts = pathname.split('/').filter(Boolean);
    if (!/^\d+$/.test(parts[0] || '')) return null;
    var size = parts[1] === 'brand' ? 4 : 2;
    if (parts.length < size) return null;
    var decoded = parts.map(function (p) {
      try { return decodeURIComponent(p); } catch (e) { return p; }
    });
    return {
      tenantId: decoded[0],
      brandName: size === 4 ? decoded[2] : null,
      customerId: decoded[size - 1],
      page: decoded[size] || null,
      base: '/' + parts.slice(0, size).join('/'),
    };
  }
  var listeners = [];
  var pages = {};
  var current = null;
  var pageListeners = [];
  var pageCleanup = null;
  var token = null;
  var authMode = 'federated';
  var state = emptyState();

  function emptyState() {
    return {
      player: null,
      balances: [],
      rewards: [],
      levels: [],
      mainLevel: null,
      missions: [],
      badges: [],
      store: { items: [], bundles: [] },
      lootboxes: [],
      tournaments: [],
      errors: {},
    };
  }

  function clone(value) {
    return value == null ? value : JSON.parse(JSON.stringify(value));
  }

  function emit() {
    listeners.slice().forEach(function (fn) {
      try {
        fn(state);
      } catch (e) {
        console.error('GamifySDK:', e);
      }
    });
  }

  function on(event, fn) {
    if (event !== 'change' || typeof fn !== 'function') return function () {};
    listeners.push(fn);
    var off = function () {
      listeners = listeners.filter(function (l) {
        return l !== fn;
      });
    };
    if (current) pageListeners.push(off);
    return off;
  }

  function uuid() {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = (Math.random() * 16) | 0;
      return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function enc(v) {
    return encodeURIComponent(String(v));
  }

  function request(method, path, body, extraHeaders) {
    var headers = { 'Content-Type': 'application/json', 'x-auth-mode': authMode };
    if (token) headers['x-user-jwt'] = token;
    Object.keys(extraHeaders || {}).forEach(function (k) {
      headers[k] = extraHeaders[k];
    });
    return fetch(live.apiUrl + path, {
      method: method,
      headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(function (res) {
      if (res.status === 404 && method === 'GET') return null;
      if (res.status === 409 && method !== 'GET') return { alreadyDone: true };
      if (!res.ok) {
        var err = new Error('GamifySDK: ' + method + ' failed with ' + res.status);
        err.status = res.status;
        throw err;
      }
      return res.text().then(function (t) {
        return t ? JSON.parse(t) : null;
      });
    });
  }

  function brandPath() {
    return enc(live.brandId);
  }

  function playerPath() {
    return enc(live.customerId);
  }

  function loadTournaments() {
    var b = brandPath();
    var p = playerPath();
    return request('GET', '/leaderboards/brand/' + b + '?type=tournament&playerId=' + p).then(function (list) {
      return Promise.all(
        (list || []).map(function (t) {
          return Promise.allSettled([
            request('GET', '/leaderboards/' + b + '/' + enc(t.id) + '/player/' + p),
            request('GET', '/leaderboard-statistics/brand/' + b + '/leaderboard/' + enc(t.id) + '/player/' + p),
          ]).then(function (r) {
            return toTournament(t, r[0].status === 'fulfilled' ? r[0].value : null, r[1].status === 'fulfilled' ? r[1].value : null);
          });
        }),
      );
    });
  }

  function timeStatus(t) {
    if (t.status === 'rewarding' || t.status === 'archived') return 'finished';
    var now = Date.now();
    if (now < new Date(t.startDate).getTime()) return 'upcoming';
    if (now > new Date(t.endDate).getTime()) return 'finished';
    return 'ongoing';
  }

  function toTournament(t, profile, position) {
    var rank = position ? position.rank : null;
    var score = profile ? profile.totalAmount : null;
    if (position && position.score !== undefined) score = position.score;
    var reward = null;
    (t.rewards || []).forEach(function (r) {
      if (rank !== null && rank >= r.rankFrom && rank <= r.rankTo) reward = r;
    });
    return {
      tournament: t,
      isEnrolled: profile ? !!profile.isEnrolled : false,
      enrolledAt: profile ? profile.enrolledAt || null : null,
      playerRank: rank,
      playerScore: score,
      participantsCount: t.participationCount == null ? null : t.participationCount,
      timeStatus: timeStatus(t),
      playerReward: reward,
    };
  }

  var loaders = {
    player: function () {
      return request('GET', '/player-profiles/brand/' + brandPath() + '/player/' + playerPath());
    },
    balances: function () {
      return request('GET', '/player-rewards/brand/' + brandPath() + '/player/' + playerPath());
    },
    badges: function () {
      return request('GET', '/player-rewards/brand/' + brandPath() + '/player/' + playerPath() + '/badges');
    },
    rewards: function () {
      return request('GET', '/rewards/brand/' + brandPath());
    },
    levels: function () {
      return request('GET', '/levels/brand/' + brandPath() + '/player/' + playerPath() + '/levels');
    },
    mainLevel: function () {
      return request('GET', '/levels/brand/' + brandPath() + '/player/' + playerPath());
    },
    missions: function () {
      return request('GET', '/missions/brand/' + brandPath() + '/player/' + playerPath());
    },
    store: function () {
      return Promise.all([
        request('GET', '/store/items/brand/' + brandPath()),
        request('GET', '/store/bundles/brand/' + brandPath()),
      ]).then(function (r) {
        return { items: r[0] || [], bundles: r[1] || [] };
      });
    },
    lootboxes: function () {
      return request('GET', '/lootboxes/brand/' + brandPath() + '/player/' + playerPath());
    },
    tournaments: loadTournaments,
  };

  var emptyValues = {
    player: null,
    mainLevel: null,
    store: { items: [], bundles: [] },
  };

  function refresh(keys) {
    if (mode !== 'live') return Promise.resolve(state);
    var wanted = keys || Object.keys(loaders);
    return Promise.all(
      wanted.map(function (key) {
        return loaders[key]()
          .then(function (value) {
            state[key] = value == null ? (key in emptyValues ? emptyValues[key] : []) : value;
            delete state.errors[key];
          })
          .catch(function (e) {
            state.errors[key] = e.status || 'network';
          });
      }),
    ).then(function () {
      emit();
      return state;
    });
  }

  function credit(rewardId, amount) {
    if (!rewardId || !amount) return;
    var reward = rewardById(rewardId);
    if (reward && reward.type === 'badge') {
      if (!state.badges.some(function (b) { return b.id === rewardId; })) state.badges.push(clone(reward));
      return;
    }
    var row = state.balances.filter(function (b) { return b.rewardTypeId === rewardId; })[0];
    if (row) row.totalAmount += amount;
    else state.balances.push({ rewardTypeId: rewardId, totalAmount: amount });
  }

  function debit(rewardId, amount) {
    var row = state.balances.filter(function (b) { return b.rewardTypeId === rewardId; })[0];
    var have = row ? row.totalAmount : 0;
    if (have < amount) {
      var err = new Error('GamifySDK: not enough balance');
      err.status = 400;
      throw err;
    }
    row.totalAmount -= amount;
  }

  function rewardById(id) {
    return state.rewards.filter(function (r) { return r.id === id; })[0] || null;
  }

  function balanceOf(id) {
    var row = state.balances.filter(function (b) { return b.rewardTypeId === id; })[0];
    return row ? row.totalAmount : 0;
  }

  function sampleAct(fn) {
    return new Promise(function (resolve, reject) {
      setTimeout(function () {
        try {
          var result = fn();
          emit();
          resolve(result === undefined ? null : result);
        } catch (e) {
          reject(e);
        }
      }, 350);
    });
  }

  function findMission(objectiveId) {
    var m = state.missions.filter(function (x) { return x.objective && x.objective.id === objectiveId; })[0];
    if (!m) {
      var err = new Error('GamifySDK: unknown mission');
      err.status = 404;
      throw err;
    }
    return m;
  }

  var levels = {
    claim: function (levelConfigId, levelNumber) {
      if (mode === 'live') {
        return request('POST', '/levels/brand/' + brandPath() + '/player/' + playerPath() + '/configs/' + enc(levelConfigId) + '/levels/' + enc(levelNumber) + '/claim')
          .then(function () { return refresh(['levels', 'mainLevel', 'balances', 'badges']); });
      }
      return sampleAct(function () {
        state.levels.concat(state.mainLevel ? [state.mainLevel] : []).forEach(function (lv) {
          if (lv.levelConfigId !== levelConfigId) return;
          var claimable = lv.claimableLevels || [];
          var hit = claimable.filter(function (c) { return c.levelNumber === levelNumber; })[0];
          if (!hit) return;
          lv.claimableLevels = claimable.filter(function (c) { return c !== hit; });
          if (lv === state.mainLevel) return;
          (hit.rewards || []).forEach(function (r) { credit(r.rewardId, r.amount); });
        });
      });
    },
  };

  var missions = {
    claim: function (objectiveId) {
      if (mode === 'live') {
        return request('POST', '/missions/brand/' + brandPath() + '/objective/' + enc(objectiveId) + '/player/' + playerPath() + '/claim')
          .then(function () { return refresh(['missions', 'balances', 'badges', 'levels', 'mainLevel']); });
      }
      return sampleAct(function () {
        var m = findMission(objectiveId);
        if (!m.mission || m.mission.status !== 'completed') return;
        m.mission.status = 'claimed';
        (m.rewards || []).forEach(function (r) { credit(r.rewardTypeId, r.amount); });
      });
    },
    unlock: function (objectiveId) {
      if (mode === 'live') {
        return request('PATCH', '/missions/brand/' + brandPath() + '/objective/' + enc(objectiveId) + '/player/' + playerPath() + '/unlock', {})
          .then(function () { return refresh(['missions', 'balances']); });
      }
      return sampleAct(function () {
        var m = findMission(objectiveId);
        if (!m.mission || m.mission.status !== 'locked') return;
        if (m.objective.unlockCurrencyId) debit(m.objective.unlockCurrencyId, m.objective.unlockAmount || 0);
        m.mission.status = 'active';
      });
    },
  };

  var tournaments = {
    enroll: function (tournamentId) {
      if (mode === 'live') {
        return request('POST', '/leaderboards/' + brandPath() + '/' + enc(tournamentId) + '/enroll/' + playerPath())
          .then(function () { return refresh(['tournaments', 'balances']); });
      }
      return sampleAct(function () {
        state.tournaments.forEach(function (t) {
          if (t.tournament.id !== tournamentId) return;
          t.isEnrolled = true;
          t.enrolledAt = new Date().toISOString();
          t.playerScore = t.playerScore || 0;
        });
      });
    },
    leaderboard: function (tournamentId, rankFrom, rankTo) {
      var from = rankFrom || 1;
      var to = rankTo || 10;
      if (mode === 'live') {
        return request('GET', '/leaderboard-statistics/brand/' + brandPath() + '/leaderboard/' + enc(tournamentId) + '/rank-range?rankFrom=' + from + '&rankTo=' + to)
          .then(function (rows) {
            return (rows || []).map(function (r) {
              return { playerId: r.playerId, playerName: r.playerName || r.playerId, rank: r.rank, score: r.score };
            });
          });
      }
      var board = (cfg.sampleLeaderboards || {})[tournamentId] || [];
      return Promise.resolve(clone(board.filter(function (r) { return r.rank >= from && r.rank <= to; })));
    },
  };

  var store = {
    buyItem: function (itemId) {
      if (mode === 'live') {
        return request('POST', '/store/items/brand/' + brandPath() + '/' + enc(itemId) + '/player/' + playerPath() + '/buy', undefined, { 'Idempotency-Key': uuid() })
          .then(function (res) { return refresh(['balances', 'store', 'badges']).then(function () { return res; }); });
      }
      return sampleAct(function () {
        var item = state.store.items.filter(function (i) { return i.id === itemId; })[0];
        if (!item || item.soldOut) throw Object.assign(new Error('GamifySDK: item unavailable'), { status: 400 });
        debit(item.priceCurrencyId, item.effectivePrice == null ? item.priceAmount : item.effectivePrice);
        credit(item.rewardId, item.rewardQuantity || 1);
        return { purchaseId: uuid() };
      });
    },
    buyBundle: function (bundleId) {
      if (mode === 'live') {
        return request('POST', '/store/bundles/brand/' + brandPath() + '/' + enc(bundleId) + '/player/' + playerPath() + '/buy', undefined, { 'Idempotency-Key': uuid() })
          .then(function (res) { return refresh(['balances', 'store', 'badges']).then(function () { return res; }); });
      }
      return sampleAct(function () {
        var bundle = state.store.bundles.filter(function (i) { return i.id === bundleId; })[0];
        if (!bundle || bundle.soldOut) throw Object.assign(new Error('GamifySDK: bundle unavailable'), { status: 400 });
        debit(bundle.priceCurrencyId, bundle.effectivePrice == null ? bundle.priceAmount : bundle.effectivePrice);
        (bundle.items || []).forEach(function (i) { credit(i.rewardId, i.rewardQuantity || 1); });
        return { purchaseId: uuid() };
      });
    },
  };

  var lootboxes = {
    open: function (lootboxId) {
      if (mode === 'live') {
        return request('POST', '/lootboxes/brand/' + brandPath() + '/' + enc(lootboxId) + '/player/' + playerPath() + '/open', undefined, { 'Idempotency-Key': uuid() })
          .then(function (res) { return refresh(['balances', 'lootboxes', 'badges']).then(function () { return res; }); });
      }
      return sampleAct(function () {
        var box = state.lootboxes.filter(function (b) { return b.id === lootboxId; })[0];
        if (!box) throw Object.assign(new Error('GamifySDK: unknown lootbox'), { status: 404 });
        (box.keys || []).forEach(function (k) {
          if (balanceOf(k.keyRewardId) < k.amount) throw Object.assign(new Error('GamifySDK: not enough keys'), { status: 400 });
        });
        (box.keys || []).forEach(function (k) { debit(k.keyRewardId, k.amount); });
        var pool = (box.prizes || []).filter(function (p) { return !p.exhausted; });
        var draws = [];
        for (var i = 0; i < (box.drawCount || 1) && pool.length; i++) {
          var p = pool[Math.floor(Math.random() * pool.length)];
          credit(p.rewardId, p.amount);
          draws.push({ prizeId: p.id, drawIndex: i, rewardId: p.rewardId, rewardName: p.rewardName, rewardIcon: p.rewardIcon, amount: p.amount });
        }
        return { openingId: uuid(), lootboxId: lootboxId, keysSpent: clone(box.keys || []), draws: draws, openedAt: new Date().toISOString() };
      });
    },
  };

  var player = {
    updateName: function (name) {
      var clean = String(name || '').trim();
      if (!clean || clean.length > 50) {
        return Promise.reject(Object.assign(new Error('GamifySDK: name must be 1-50 characters'), { status: 400 }));
      }
      if (mode === 'live') {
        return request('PUT', '/player-profiles/brand/' + brandPath() + '/player/' + playerPath() + '/name', { name: clean })
          .then(function () { return refresh(['player']); });
      }
      return sampleAct(function () {
        state.player = Object.assign({}, state.player, { name: clean });
      });
    },
  };

  function asset(path) {
    if (!path) return '';
    if (/^(https?:|data:|blob:)/.test(path)) return path;
    return cdnUrl + '/' + String(path).replace(/^\/+/, '');
  }

  function breakpoint() {
    var w = window.innerWidth;
    if (w < 640) return 'sm';
    if (w < 1024) return 'md';
    if (w < 1440) return 'lg';
    return 'xl';
  }

  function definePage(name, mount) {
    pages[name] = mount;
    if (name === current) mountPage(name);
  }

  function runScripts(root) {
    root.querySelectorAll('script').forEach(function (old) {
      var s = document.createElement('script');
      s.textContent = old.textContent;
      old.replaceWith(s);
    });
  }

  function unmountPage() {
    pageListeners.forEach(function (off) { off(); });
    pageListeners = [];
    if (typeof pageCleanup === 'function') {
      try { pageCleanup(); } catch (e) { console.error('GamifySDK:', e); }
    }
    pageCleanup = null;
  }

  function mountPage(name) {
    var outlet = document.querySelector('[data-gamify-outlet]');
    var tpl = document.querySelector('template[data-gamify-page="' + name + '"]');
    if (!outlet || !tpl) return;
    unmountPage();
    current = name;
    var root = document.createElement('div');
    root.setAttribute('data-gamify-page-root', name);
    root.appendChild(document.importNode(tpl.content, true));
    outlet.innerHTML = '';
    outlet.setAttribute('data-gamify-current', name);
    outlet.appendChild(root);
    runScripts(root);
    document.querySelectorAll('[data-gamify-nav]').forEach(function (el) {
      el.classList.toggle('is-active', el.getAttribute('data-gamify-nav') === name);
      if (el.getAttribute('data-gamify-nav') === name) el.setAttribute('aria-current', 'page');
      else el.removeAttribute('aria-current');
    });
    var mount = pages[name];
    if (typeof mount === 'function') {
      try {
        pageCleanup = mount(root, api);
      } catch (e) {
        console.error('GamifySDK: page "' + name + '" failed to mount', e);
      }
    }
    window.dispatchEvent(new CustomEvent('gamify:navigate', { detail: { page: name } }));
  }

  function pageUrl(name) {
    return route.base + '/' + enc(name) + location.search;
  }

  function navigate(name) {
    if ((cfg.pages || []).indexOf(name) === -1) return;
    if (route) {
      if (location.pathname !== route.base + '/' + enc(name)) history.pushState(null, '', pageUrl(name));
      mountPage(name);
    } else if (location.hash !== '#' + name) location.hash = name;
    else mountPage(name);
  }

  function pageFromLocation() {
    var name = route ? (parseRoute(location.pathname) || {}).page : location.hash.replace(/^#/, '');
    return (cfg.pages || []).indexOf(name) === -1 ? cfg.defaultPage : name;
  }

  function wireNav() {
    document.addEventListener('click', function (e) {
      var el = e.target.closest && e.target.closest('[data-gamify-nav]');
      if (!el) return;
      e.preventDefault();
      navigate(el.getAttribute('data-gamify-nav'));
    });
    window.addEventListener(route ? 'popstate' : 'hashchange', function () { mountPage(pageFromLocation()); });
    var last = breakpoint();
    window.addEventListener('resize', function () {
      var now = breakpoint();
      if (now !== last) {
        last = now;
        emit();
      }
    });
  }

  function waitForToken() {
    var params = new URLSearchParams(location.search);
    if (params.get('token')) {
      token = params.get('token');
      authMode = params.get('authMode') || authMode;
      return Promise.resolve();
    }
    if (window.parent === window) return Promise.resolve();
    return new Promise(function (resolve) {
      var done = false;
      window.addEventListener('message', function (event) {
        var data = event.data || {};
        if (event.source !== window.parent || data.type !== 'INIT') return;
        token = data.token || token;
        authMode = data.authMode || authMode;
        if (!done) {
          done = true;
          resolve();
        }
      });
      window.parent.postMessage({ type: 'READY' }, '*');
      setTimeout(function () {
        if (!done) {
          done = true;
          resolve();
        }
      }, 1500);
    });
  }

  function brandPathFor(r) {
    return r.brandName === null
      ? '/brands/default/' + enc(r.tenantId)
      : '/brands/tenant/' + enc(r.tenantId) + '/name/' + enc(r.brandName);
  }

  function resolveBrand() {
    if (!route) return Promise.resolve(true);
    live.customerId = route.customerId;
    var lastError = 404;
    return hosts.reduce(function (found, host) {
      return found.then(function (done) {
        if (done) return true;
        live.apiUrl = host.apiUrl;
        return request('GET', brandPathFor(route)).then(function (brand) {
          if (!brand || !brand.id) return false;
          live.brandId = brand.id;
          cdnUrl = host.cdnUrl || cdnUrl;
          return true;
        }).catch(function (e) {
          lastError = e.status || 'network';
          return false;
        });
      });
    }, Promise.resolve(false)).then(function (done) {
      if (!done) state.errors.brand = lastError;
      return done;
    });
  }

  function loadSample() {
    Object.assign(state, clone(cfg.sample || {}), { errors: {} });
    if (route && state.player) state.player.id = route.customerId;
    return Promise.resolve(state);
  }

  function loadLive() {
    return waitForToken()
      .then(resolveBrand)
      .then(function (found) {
        if (found) return refresh();
        console.error('GamifySDK: ' + (route.brandName === null ? 'the default brand' : 'brand "' + route.brandName + '"') + ' was not found on tenant ' + route.tenantId + ' (' + state.errors.brand + ')');
        return state;
      });
  }

  var ready = new Promise(function (resolve) {
    function boot() {
      wireNav();
      var start = mode === 'live' ? loadLive() : loadSample();
      start.then(function () {
        var page = pageFromLocation();
        if (route && (parseRoute(location.pathname) || {}).page !== page) history.replaceState(null, '', pageUrl(page));
        mountPage(page);
        emit();
        resolve(api);
      });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  });

  var api = {
    version: cfg.sdkVersion || '0',
    get mode() { return mode; },
    get state() { return state; },
    get page() { return current; },
    get pages() { return (cfg.pages || []).slice(); },
    get route() { return route ? { tenantId: route.tenantId, brandName: route.brandName, customerId: route.customerId } : null; },
    get breakpoint() { return breakpoint(); },
    ready: function (fn) { return typeof fn === 'function' ? ready.then(fn) : ready; },
    on: on,
    refresh: refresh,
    definePage: definePage,
    navigate: navigate,
    reward: rewardById,
    balance: balanceOf,
    asset: asset,
    levels: levels,
    missions: missions,
    tournaments: tournaments,
    store: store,
    lootboxes: lootboxes,
    player: player,
  };

  window.GamifySDK = api;
})();
