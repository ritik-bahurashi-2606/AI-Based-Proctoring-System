/**
 * proctoring_common.js  —  MyProctor.ai
 * Smart real-time proctoring: warnings, audio recording, smart response handling.
 */
(function () {
  /* ── Test-ID helper ──────────────────────────────────────────────────── */
  if (typeof window !== 'undefined' && typeof tid !== 'undefined' && tid && !window.tid) {
    window.tid = tid;
  }
  function getTestId() {
    if (typeof window !== 'undefined' && window.tid) return window.tid;
    if (typeof tid !== 'undefined' && tid)           return tid;
    return '';
  }

  /* ── State ───────────────────────────────────────────────────────────── */
  var cameraStream         = null;
  var audioContext         = null;
  var analyser             = null;
  var microphone           = null;
  var audioProcessor       = null;
  var audioValues          = 0;
  var audioLength          = 1;
  var mediaRecorder        = null;
  var audioChunks          = [];
  var recordingAudio       = false;
  var audioSilenceTimer    = null;
  var lastAudioPid         = '';
  var warningCounts        = {};
  var lastWarningAt        = {};

  /* Expose key functions globally so app.js can call them */
  /* (set after functions are defined — see bottom of IIFE) */

  /* ── Configurable thresholds ─────────────────────────────────────────── */
  var AUDIO_TRIGGER_LEVEL      = 18;
  var AUDIO_SILENCE_TIMEOUT_MS = 4000;   // stop recording after 4 s of silence
  var WARNING_COOLDOWN_MS      = 5000;   // min ms between same-type toasts
  var SNAP_INTERVAL_MS         = 2000;   // how often to capture a frame

  /* ═══════════════════════════════════════════════════════════════════════
   *  WARNING TOAST SYSTEM
   * ═══════════════════════════════════════════════════════════════════════ */
  function showProctorWarning(message, eventType) {
    eventType = eventType || 'warning';
    var now = Date.now();

    /* Per-type cooldown — don't spam same warning */
    if (lastWarningAt[eventType] && now - lastWarningAt[eventType] < WARNING_COOLDOWN_MS) {
      return;
    }
    lastWarningAt[eventType] = now;
    warningCounts[eventType] = (warningCounts[eventType] || 0) + 1;
    var count = warningCounts[eventType];

    var text = message;
    if (count > 1) text += ' [' + count + 'x]';
    if (count >= 3) text += ' Repeated violations will be escalated to your examiner.';

    /* ── SweetAlert2 toast (preferred) ───────────────────────────────── */
    if (window.Swal) {
      Swal.fire({
        toast:            true,
        position:         'top-end',
        icon:             count >= 3 ? 'error' : 'warning',
        title:            text,
        showConfirmButton: false,
        timer:            5000,
        timerProgressBar: true,
        customClass: {
          popup: 'proctor-toast'
        }
      });
      return;
    }

    /* ── Fallback: custom banner ─────────────────────────────────────── */
    _showFallbackBanner(text, count >= 3 ? '#dc3545' : '#ff9800');
  }

  function _showFallbackBanner(text, color) {
    var banner = document.getElementById('proctor-warning-banner');
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'proctor-warning-banner';
      banner.style.cssText = [
        'position:fixed', 'top:10px', 'right:10px', 'z-index:99999',
        'padding:12px 18px', 'border-radius:8px', 'color:#fff',
        'font-size:14px', 'font-weight:600', 'box-shadow:0 4px 15px rgba(0,0,0,.35)',
        'max-width:340px', 'line-height:1.4', 'transition:opacity .3s'
      ].join(';');
      document.body.appendChild(banner);
    }
    banner.style.background = color;
    banner.style.opacity    = '1';
    banner.innerHTML = '<span style="font-size:1.1em;margin-right:6px;">⚠</span>' + text;
    if (banner._hideTimer) clearTimeout(banner._hideTimer);
    banner._hideTimer = setTimeout(function () {
      banner.style.opacity = '0';
    }, 5000);
  }

  /* ═══════════════════════════════════════════════════════════════════════
   *  RESPONSE HANDLER — processes what /video_feed returns
   * ═══════════════════════════════════════════════════════════════════════ */
  function handleProctorResponse(response) {
    if (!response || response.status === 'error') return;

    /* Show all server-determined warnings */
    var warnings = response.warnings || response.events || [];
    warnings.forEach(function (event) {
      if (event && event.message) {
        showProctorWarning(event.message, event.event_type);
      }
    });

    /* Trigger audio recording if audio is suspicious */
    if (response.audio_suspicious) {
      if (response.pid) lastAudioPid = String(response.pid);
      startAudioEvidenceRecording();
    }
  }

  /* ═══════════════════════════════════════════════════════════════════════
   *  AUDIO EVIDENCE RECORDING
   * ═══════════════════════════════════════════════════════════════════════ */
  function uploadAudioEvidence(blob) {
    if (!blob || !getTestId()) return;
    var formData = new FormData();
    formData.append('testid',     getTestId());
    formData.append('event_type', 'suspicious_audio');
    if (lastAudioPid) formData.append('pid', lastAudioPid);
    formData.append('audio', blob, 'audio-evidence.webm');
    fetch('/upload_audio_evidence', { method: 'POST', body: formData })
      .catch(function (err) { console.warn('Audio evidence upload failed:', err); });
  }

  function startAudioEvidenceRecording() {
    if (!cameraStream || typeof MediaRecorder === 'undefined') return;

    /* Start a fresh recording if not already active */
    if (!recordingAudio) {
      try {
        audioChunks = [];
        var options = (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported('audio/webm'))
          ? { mimeType: 'audio/webm' } : undefined;
        mediaRecorder = new MediaRecorder(cameraStream, options);
        mediaRecorder.ondataavailable = function (e) {
          if (e.data && e.data.size > 0) audioChunks.push(e.data);
        };
        mediaRecorder.onstop = function () {
          uploadAudioEvidence(new Blob(audioChunks, { type: 'audio/webm' }));
          audioChunks = [];
        };
        mediaRecorder.start();
        recordingAudio = true;
      } catch (err) {
        console.warn('Audio recorder could not start:', err);
        return;
      }
    }

    /* Reset silence timer — stop after sustained quiet */
    if (audioSilenceTimer) clearTimeout(audioSilenceTimer);
    audioSilenceTimer = setTimeout(function () {
      if (mediaRecorder && recordingAudio && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
      }
      recordingAudio = false;
    }, AUDIO_SILENCE_TIMEOUT_MS);
  }

  function currentAudioAverage() { return audioValues / (audioLength || 1); }

  /* ═══════════════════════════════════════════════════════════════════════
   *  CAMERA + MICROPHONE STREAM
   * ═══════════════════════════════════════════════════════════════════════ */
  window.startStreaming = function () {
    var streamEl = document.getElementById('stream');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showProctorWarning('Warning: Camera or microphone is not supported in this browser.', 'media_unsupported');
      return;
    }
    if (cameraStream) return;

    navigator.mediaDevices.getUserMedia({ video: true, audio: true })
      .then(function (mediaStream) {
        cameraStream = mediaStream;
        window._proctoringStream = mediaStream;  // expose for app.js captureSnapshot
        if (streamEl) {
          streamEl.srcObject = mediaStream;
          streamEl.play().catch(function (e) { console.warn('Video play failed:', e); });
        }

        /* ── Track lifecycle warnings ────────────────────────────────── */
        mediaStream.getVideoTracks().forEach(function (track) {
          track.onended = function () {
            showProctorWarning('Warning: Camera disabled. Re-enable your camera to continue.', 'camera_disabled');
          };
          track.onmute = function () {
            showProctorWarning('Warning: Camera visibility issue detected.', 'camera_obstruction');
          };
        });
        mediaStream.getAudioTracks().forEach(function (track) {
          track.onended = function () {
            showProctorWarning('Warning: Microphone disabled during exam.', 'microphone_disabled');
          };
          track.onmute = function () {
            showProctorWarning('Warning: Microphone muted during exam.', 'microphone_disabled');
          };
        });

        /* ── Audio analysis for voice detection ──────────────────────── */
        try {
          audioContext   = new (window.AudioContext || window.webkitAudioContext)();
          analyser       = audioContext.createAnalyser();
          microphone     = audioContext.createMediaStreamSource(mediaStream);
          audioProcessor = audioContext.createScriptProcessor(2048, 1, 1);
          analyser.smoothingTimeConstant = 0.8;
          analyser.fftSize = 1024;
          microphone.connect(analyser);
          analyser.connect(audioProcessor);
          audioProcessor.connect(audioContext.destination);
          audioProcessor.onaudioprocess = function () {
            var arr = new Uint8Array(analyser.frequencyBinCount);
            analyser.getByteFrequencyData(arr);
            audioValues = 0;
            audioLength = arr.length || 1;
            for (var i = 0; i < audioLength; i++) audioValues += arr[i];
            if (currentAudioAverage() >= AUDIO_TRIGGER_LEVEL) {
              showProctorWarning('Warning: Suspicious audio activity detected.', 'suspicious_audio');
              startAudioEvidenceRecording();
            }
          };
        } catch (err) {
          console.warn('Audio processing failed:', err);
          showProctorWarning('Warning: Microphone access issue detected.', 'microphone_disabled');
        }
      })
      .catch(function (err) {
        console.error('Unable to access camera/microphone:', err);
        showProctorWarning('Warning: Camera and microphone permission is required during the exam.', 'media_permission');
      });
  };

  window.stopStreaming = function () {
    if (cameraStream) {
      cameraStream.getTracks().forEach(function (t) { t.stop(); });
      cameraStream = null;
      window._proctoringStream = null;
    }
  };

  /* ── Globally expose key functions for app.js ────────────────────────── */
  window.showProctorWarning          = showProctorWarning;
  window.startAudioEvidenceRecording = startAudioEvidenceRecording;

  /* ═══════════════════════════════════════════════════════════════════════
   *  FRAME CAPTURE & SEND
   * ═══════════════════════════════════════════════════════════════════════ */
  window.captureSnapshot = function () {
    var streamEl = document.getElementById('stream');
    var capture  = document.getElementById('capture');
    if (cameraStream && streamEl && capture) {
      var ctx = capture.getContext('2d');
      ctx.drawImage(streamEl, 0, 0, capture.width, capture.height);
      var dataUrl = capture.toDataURL('image/jpeg', 0.82);
      var base64  = dataUrl.replace(/^data:image\/(jpeg|jpg);base64,/, '');
      $.ajax({
        url:      '/video_feed',
        type:     'POST',
        dataType: 'json',
        data: {
          data: {
            imgData:  base64,
            voice_db: currentAudioAverage(),
            testid:   getTestId()
          }
        },
        success: handleProctorResponse,
        error: function (xhr, status, err) {
          console.warn('video_feed request failed:', status, err);
        }
      });
    }
    setTimeout(window.captureSnapshot, SNAP_INTERVAL_MS);
  };

  /* ═══════════════════════════════════════════════════════════════════════
   *  BROWSER / WINDOW EVENTS
   * ═══════════════════════════════════════════════════════════════════════ */

  /* Tab switching */
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      showProctorWarning('Warning: Tab switching is prohibited during the exam.', 'tab_switch');
      var tidv = getTestId();
      if (tidv) {
        $.ajax({
          data: { testid: tidv, event_type: 'tab_switch' },
          type: 'POST', url: '/window_event', dataType: 'json',
          success: handleProctorResponse,
          error: function (xhr, s, e) { console.warn('window_event (tab) failed:', s, e); }
        });
      }
    }
  });

  /* Browser minimization / focus loss */
  var blurServerTimer = null;
  window.addEventListener('blur', function () {
    showProctorWarning('Warning: Browser minimization or focus loss detected.', 'browser_minimized');
    if (blurServerTimer) clearTimeout(blurServerTimer);
    blurServerTimer = setTimeout(function () {
      if (document.hidden) return;
      var tidv = getTestId();
      if (!tidv) return;
      $.ajax({
        data: { testid: tidv, event_type: 'browser_minimized' },
        type: 'POST', url: '/window_event', dataType: 'json',
        success: handleProctorResponse,
        error: function (xhr, s, e) { console.warn('window_event (blur) failed:', s, e); }
      });
    }, 700);
  });

  /* Network disconnection */
  window.addEventListener('offline', function () {
    showProctorWarning('Warning: Network disconnection detected. Your exam may be affected.', 'network_disconnection');
  });
  window.addEventListener('online', function () {
    /* Silent — just log; no warning needed for reconnection */
    console.info('Network reconnected.');
  });

  /* Screen sharing stopped (if started via getDisplayMedia) */
  if (navigator.mediaDevices) {
    // Screen-share track end is detected at the app level when started;
    // here we surface a global hook that exam pages can call after getDisplayMedia
    window.onScreenShareEnded = function () {
      showProctorWarning('Warning: Screen sharing stopped during the exam.', 'screen_share_stopped');
    };
  }

  /* ── Inject minimal toast style if SweetAlert2 not present ──────────── */
  (function injectFallbackStyle() {
    if (document.getElementById('proctor-toast-style')) return;
    var s = document.createElement('style');
    s.id  = 'proctor-toast-style';
    s.textContent = [
      '.proctor-toast { font-size: 14px !important; }',
      '#proctor-warning-banner { transition: opacity .3s; }'
    ].join('\n');
    document.head.appendChild(s);
  }());

})();
