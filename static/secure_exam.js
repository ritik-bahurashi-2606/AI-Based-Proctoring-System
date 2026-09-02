(function () {
  'use strict';

  function post(url, body, keepalive) {
    return fetch(url, {
      method: 'POST', credentials: 'same-origin', keepalive: !!keepalive,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.text().then(function (text) {
        var result;
        try { result = JSON.parse(text); } catch (error) {
          throw new Error('The server returned an invalid response.');
        }
        if (!response.ok) {
          throw new Error(result.message || 'The secure exam request failed.');
        }
        return result;
      });
    });
  }

  function clientInfo() {
    return { userAgent: navigator.userAgent, language: navigator.language, platform: navigator.platform };
  }

  function browserCheck(policy, mediaReady) {
    var supported = !!(window.fetch && window.Promise && document.fullscreenEnabled !== undefined);
    var fullscreen = !!document.fullscreenEnabled;
    var mediaSupport = mediaReady !== undefined
      ? mediaReady
      : !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    var singleDisplay = (window.screen && window.screen.width >= 1024);
    
    return [
      { key: 'browser', title: 'Supported Secure Browser', ok: supported, required: true, detail: supported ? 'Modern Chrome/Edge/Firefox environment verified.' : 'Use a current Chrome, Edge, or Firefox browser.' },
      { key: 'media', title: 'Camera & Microphone Hardware', ok: mediaSupport, required: true, detail: mediaSupport ? 'Camera and microphone permissions are available.' : 'Allow camera and microphone permissions, then run diagnostics again.' },
      { key: 'native', title: 'Secure Exam Client', ok: !policy.requireNativeClient, required: !!policy.requireNativeClient, detail: policy.requireNativeClient ? 'The required Secure Exam Client is not available in this browser.' : 'No native Secure Exam Client is required for this exam.' },
      { key: 'connection', title: 'Server Network Connection', ok: navigator.onLine, required: true, detail: navigator.onLine ? 'Connected to the exam server with active heartbeat.' : 'Reconnect to the internet, then try again.' },
      { key: 'fullscreen', title: 'Fullscreen Examination Environment', ok: !policy.requireFullscreen || fullscreen, required: !!policy.requireFullscreen, detail: fullscreen ? 'Fullscreen environment locking available.' : 'Fullscreen is unavailable in this browser.' },
      { key: 'display', title: 'Display & Screen Resolution', ok: singleDisplay, required: false, detail: singleDisplay ? 'Screen resolution satisfies minimum exam requirements.' : 'Low screen resolution detected.' },
      { key: 'tabs_guidance', title: 'Browser Tabs & Application Compliance', ok: true, required: false, detail: 'Single exam tab policy active. Secondary tabs & background recording tools prohibited.' }
    ];
  }

  function requestFullscreen() {
    var root = document.documentElement;
    if (root.requestFullscreen) return root.requestFullscreen();
    return Promise.resolve();
  }

  function renderReadiness(items) {
    var list = document.getElementById('readiness-items');
    var score = document.getElementById('readiness-score');
    var bar = document.getElementById('readiness-bar');
    var start = document.getElementById('secure-start');
    if (!list) return;
    var required = items.filter(function (item) { return item.required; });
    var passed = items.filter(function (item) { return item.ok; }).length;
    var percentage = Math.round((passed / items.length) * 100);
    var blocked = required.some(function (item) { return !item.ok; });
    score.textContent = 'Readiness: ' + percentage + '%';
    bar.style.width = percentage + '%';
    list.innerHTML = items.map(function (item) {
      var state = item.ok ? 'pass' : (item.required ? 'block' : 'warn');
      return '<div class="secure-check secure-check-' + state + '"><span class="secure-check-icon" aria-hidden="true">' + (item.ok ? '&#10003;' : '!') + '</span><div><strong>' + item.title + '</strong><small>' + item.detail + '</small></div></div>';
    }).join('');
    start.disabled = blocked;
    return { blocked: blocked, readiness: {
      fullscreenAvailable: items.find(function (item) { return item.key === 'fullscreen'; }).ok,
      nativeClientVerified: items.find(function (item) { return item.key === 'native'; }).ok,
      browserSupported: items.find(function (item) { return item.key === 'browser'; }).ok,
      online: navigator.onLine
    }};
  }

  function initReadiness() {
    var config = window.SECURE_READINESS_CONFIG;
    if (!config) return;
    var current;
    var message = document.getElementById('readiness-message');
    var retry = document.getElementById('secure-retry');
    var start = document.getElementById('secure-start');

    function checkMedia() {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        return Promise.resolve(false);
      }
      return navigator.mediaDevices.getUserMedia({ video: true, audio: true })
        .then(function (mediaStream) {
          mediaStream.getTracks().forEach(function (track) { track.stop(); });
          return true;
        })
        .catch(function () { return false; });
    }

    function check() {
      if (retry) retry.disabled = true;
      if (start) start.disabled = true;
      if (message) {
        message.className = 'alert alert-info mt-3';
        message.textContent = 'Checking camera, microphone, network, browser, and display...';
      }
      return checkMedia().then(function (mediaReady) {
        current = renderReadiness(browserCheck(config.policy, mediaReady));
        if (message) {
          message.className = current.blocked ? 'alert alert-warning mt-3' : 'alert alert-success mt-3';
          message.textContent = current.blocked
            ? 'Complete the required checks above before starting the secure exam.'
            : 'All required checks passed. You can start the secure exam.';
        }
        if (retry) retry.disabled = false;
        return current;
      });
    }

    check();
    retry.addEventListener('click', check);
    start.addEventListener('click', function () {
      start.disabled = true;
      requestFullscreen().catch(function () {}).then(function () {
        return check();
      }).then(function () {
        if (current.blocked) {
          start.disabled = false;
          return;
        }
        post('/api/secure-exam/' + encodeURIComponent(config.examId) + '/start', { readiness: current.readiness, client: clientInfo() })
          .then(function (result) {
            if (result.status === 'success') window.location.assign(result.examUrl);
            else {
              message.textContent = result.message || 'The secure exam could not start.';
              message.className = 'alert alert-danger mt-3';
              start.disabled = false;
            }
          })
          .catch(function () {
            message.textContent = 'Unable to reach the exam server. Check your connection and try again.';
            message.className = 'alert alert-danger mt-3';
            start.disabled = false;
          });
      });
    });
  }

  function initExam() {
    var config = window.SECURE_EXAM_CONFIG;
    if (!config || !config.sessionId) return;
    var eventUrl = '/api/secure-exam/' + encodeURIComponent(config.examId) + '/events';
    var ended = false;
    var focusLostAt = 0;
    var lastEventAt = {};

    function report(eventType, explanation, metadata) {
      var now = Date.now();
      if (lastEventAt[eventType] && now - lastEventAt[eventType] < 2500) return;
      lastEventAt[eventType] = now;
      post(eventUrl, { sessionId: config.sessionId, eventType: eventType, explanation: explanation, metadata: metadata || {}, source: 'browser' })
        .then(function (result) { showWarning(eventType, explanation, result); })
        .catch(function () {});
    }

    function showWarning(eventType, explanation, result) {
      if (eventType === 'FOCUS_RESTORED') return;
      var existing = document.getElementById('secure-warning');
      if (existing) existing.remove();
      var warning = document.createElement('div');
      warning.id = 'secure-warning'; warning.className = 'secure-warning';
      warning.innerHTML = '<div class="secure-warning-panel"><h2>Secure Mode Warning</h2><p>' + explanation + '</p><p>This event has been recorded. Your exam remains available.</p><button type="button" class="btn btn-primary">Return to Exam</button></div>';
      warning.querySelector('button').addEventListener('click', function () { warning.remove(); if (document.fullscreenEnabled && !document.fullscreenElement) requestFullscreen().catch(function () {}); });
      document.body.appendChild(warning);
      if (result && result.action && result.action !== 'continue') warning.querySelector('p').textContent = 'Secure mode has been paused according to the configured exam policy. Contact the exam administrator.';
    }

    function addCenter() {
      var panel = document.createElement('aside');
      panel.className = 'secure-center';
      panel.innerHTML = '<h2>Secure Mode Active</h2><div class="secure-center-row"><span>Exam connection</span><b id="secure-network">CONNECTED</b></div><div class="secure-center-row"><span>Websites</span><b>EXAM ONLY</b></div><div class="secure-center-row"><span>Copy / paste</span><b>RESTRICTED</b></div><div class="secure-center-row"><span>Printing</span><b>RESTRICTED</b></div><div class="secure-center-row"><span>Session status</span><b>NORMAL</b></div><button id="secure-emergency" type="button" class="btn btn-sm btn-outline-light mt-3">Emergency Exit</button>';
      document.body.appendChild(panel);
      panel.querySelector('#secure-emergency').addEventListener('click', function () {
        var reason = window.prompt('Emergency reason: medical, technical, device, internet, or other');
        if (!reason) return;
        post('/api/secure-exam/' + encodeURIComponent(config.examId) + '/emergency-exit', { sessionId: config.sessionId, reason: reason }).then(function () { window.location.assign('/student_index'); });
      });
    }

    function stop() {
      if (ended) return; ended = true;
      if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(function () {});
    }

    window.SecureExam = { end: stop, report: report };
    addCenter();
    window.setInterval(function () { post('/api/secure-exam/' + encodeURIComponent(config.examId) + '/heartbeat', { sessionId: config.sessionId }).catch(function () {}); }, 15000);
    document.addEventListener('visibilitychange', function () { if (document.hidden) { focusLostAt = Date.now(); report('FOCUS_LOST', 'The examination window lost focus. Please remain in the secure examination environment.'); } else if (focusLostAt) { report('FOCUS_RESTORED', 'The examination window regained focus.', { durationMs: Date.now() - focusLostAt }); focusLostAt = 0; } });
    window.addEventListener('blur', function () { report('FOCUS_LOST', 'The examination window lost focus. Please remain in the secure examination environment.'); });
    document.addEventListener('fullscreenchange', function () { if (!document.fullscreenElement && config.policy.requireFullscreen && !ended) report('FULLSCREEN_EXITED', 'Fullscreen was exited. Please return to fullscreen to continue securely.'); });
    window.addEventListener('offline', function () { document.getElementById('secure-network').textContent = 'RECONNECTING'; report('NETWORK_DISCONNECTED', 'Connection to the exam server was interrupted. Your exam remains protected while we reconnect.'); });
    window.addEventListener('online', function () { document.getElementById('secure-network').textContent = 'CONNECTED'; report('NETWORK_RECONNECTED', 'Connection to the exam server was restored.'); });
    document.addEventListener('copy', function (event) { if (!config.policy.allowCopy) { event.preventDefault(); report('COPY_ATTEMPT', 'Copying is not allowed during this examination.'); } });
    document.addEventListener('paste', function (event) { if (!config.policy.allowPaste) { event.preventDefault(); report('PASTE_ATTEMPT', 'Pasting is not allowed during this examination.'); } });
    document.addEventListener('keydown', function (event) { if (!config.policy.allowPrinting && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'p') { event.preventDefault(); report('PRINT_ATTEMPT', 'Printing is not allowed during this examination.'); } if ((event.ctrlKey || event.metaKey) && ['l', 't', 'n', 'w'].indexOf(event.key.toLowerCase()) >= 0) { event.preventDefault(); report('NEW_WINDOW_ATTEMPT', 'Opening a new tab or window is not allowed during this examination.'); } });
    window.addEventListener('beforeunload', function () { if (!ended) report('FOCUS_LOST', 'The exam page attempted to unload.'); });
  }

  document.addEventListener('DOMContentLoaded', function () { initReadiness(); initExam(); });
}());
