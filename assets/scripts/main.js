//* ======================== Deferred Decorative Art ===================== */
(function setupDeferredArt() {
  var images = Array.prototype.slice.call(document.querySelectorAll('img[data-src]'));
  if (!images.length) return;

  function loadImage(image) {
    if (!image.dataset.src) return;
    image.src = image.dataset.src;
    image.removeAttribute('data-src');
  }

  function scheduleImage(image) {
    window.setTimeout(function() {
      loadImage(image);
    }, 120);
  }

  if (!('IntersectionObserver' in window)) {
    images.forEach(scheduleImage);
    return;
  }

  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (!entry.isIntersecting) return;
      observer.unobserve(entry.target);
      scheduleImage(entry.target);
    });
  }, {rootMargin: '160px 0px'});

  images.forEach(function(image) {
    observer.observe(image);
  });
})();

//* ======================== Demo Showcase ===================== */
(function setupDemoShowcase() {
  var showcase = document.querySelector('.demo-showcase');
  if (!showcase) return;

  var modeSwitch = showcase.querySelector('.demo-mode-switch');
  var buttons = Array.prototype.slice.call(showcase.querySelectorAll('[data-demo-target]'));
  var panels = Array.prototype.slice.call(showcase.querySelectorAll('[data-demo-panel]'));
  var videoWraps = Array.prototype.slice.call(showcase.querySelectorAll('[data-video-src]'));

  function loadAndPlay(video) {
    if (!video) return;

    var wrap = video.closest('[data-video-src]');
    if (!wrap) return;

    if (video.dataset.loaded !== 'true') {
      if (!video.poster && wrap.dataset.videoPoster) {
        video.poster = wrap.dataset.videoPoster;
      }
      var source = document.createElement('source');
      source.src = wrap.dataset.videoSrc;
      source.type = 'video/mp4';
      video.appendChild(source);
      video.dataset.loaded = 'true';
      video.controls = true;
      wrap.classList.add('is-loaded');
      video.load();
    }

    video.play().catch(function() {});
  }

  videoWraps.forEach(function(wrap) {
    var video = wrap.querySelector('video');
    var trigger = wrap.querySelector('.demo-video-trigger');
    if (!video) return;

    if (trigger) {
      trigger.addEventListener('click', function() {
        loadAndPlay(video);
        video.focus({preventScroll: true});
      });
    }

    video.addEventListener('click', function() {
      if (video.dataset.loaded !== 'true') loadAndPlay(video);
    });
  });

  function activateDemo(name, moveFocus) {
    modeSwitch.dataset.active = name;

    buttons.forEach(function(button) {
      var isActive = button.dataset.demoTarget === name;
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-selected', String(isActive));
      button.tabIndex = isActive ? 0 : -1;
      if (isActive && moveFocus) button.focus();
    });

    panels.forEach(function(panel) {
      var isActive = panel.dataset.demoPanel === name;
      var video = panel.querySelector('video');

      panel.hidden = !isActive;
      panel.classList.toggle('is-active', isActive);
      panel.setAttribute('aria-hidden', String(!isActive));

      if (!video) return;
      if (isActive) {
        if (video.dataset.loaded === 'true') {
          video.currentTime = 0;
          video.play().catch(function() {});
        }
      } else {
        video.pause();
      }
    });

  }

  buttons.forEach(function(button, index) {
    button.addEventListener('click', function() {
      activateDemo(button.dataset.demoTarget, false);
    });

    button.addEventListener('keydown', function(event) {
      if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      var direction = event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 1;
      var nextIndex = (index + direction + buttons.length) % buttons.length;
      activateDemo(buttons[nextIndex].dataset.demoTarget, true);
    });
  });
})();

//* ======================== Video Control ===================== */
function ToggleVideo(x) {
  var videos = document.getElementsByClassName(x + '-video');
  for (var i = 0; i < videos.length; i++) {
      if (videos[i].paused) {
          videos[i].play();
      } else {
          videos[i].pause();
      }
  }
};


function SlowVideo(x) {
  var videos = document.getElementsByClassName(x + '-video');
  for (var i = 0; i < videos.length; i++) {
    videos[i].playbackRate = videos[i].playbackRate * 0.9;
    videos[i].play();
  }
  
  var msg = document.getElementById(x + '-msg');
  msg.innerHTML = 'Speed: ' + '×' + videos[0].playbackRate.toFixed(2);

  msg.classList.add("fade-in-out");
  msg.style.animation = 'none';
  msg.offsetHeight; /* trigger reflow */
  msg.style.animation = null; };


function FastVideo(x) {
  var videos = document.getElementsByClassName(x + '-video');
  for (var i = 0; i < videos.length; i++) {
    videos[i].playbackRate = videos[i].playbackRate / 0.9;
    videos[i].play();
  }

  var msg = document.getElementById(x + '-msg');
  msg.innerHTML = 'Speed: ' + '×' + videos[0].playbackRate.toFixed(2);

  msg.classList.add("fade-in-out");
  msg.style.animation = 'none';
  msg.offsetHeight; /* trigger reflow */
  msg.style.animation = null; 
};

function RestartVideo(x) {
  var videos = document.getElementsByClassName(x + '-video');
  for (var i = 0; i < videos.length; i++) {
    videos[i].pause();
    videos[i].playbackRate = 1.0;
    videos[i].currentTime = 0;
    videos[i].play();
  }
  
  var msg = document.getElementById(x + '-msg');
  msg.innerHTML = 'Speed: ' + '×' + videos[0].playbackRate.toFixed(2);

  msg.classList.add("fade-in-out");
  msg.style.animation = 'none';
  msg.offsetHeight; /* trigger reflow */
  msg.style.animation = null; 
};

//* ======================== Hero Video Zoom ===================== */
(function setupHeroVideoZoom() {
  var hero = document.getElementById('first-content');
  var frame = document.querySelector('[data-hero-video-frame]');
  if (!hero || !frame) return;

  var video = frame.querySelector('.hero-video');
  var expandButton = frame.querySelector('.hero-video-expand');
  var fullscreenButton = frame.querySelector('[data-hero-video-action="fullscreen"]');
  var collapseButton = frame.querySelector('[data-hero-video-action="collapse"]');
  var fullscreenIcon = fullscreenButton && fullscreenButton.querySelector('i');
  var fullscreenLabel = fullscreenButton && fullscreenButton.querySelector('span');
  var transitionDuration = 620;
  var isExpanded = false;
  var isAnimating = false;
  var originRect = null;

  function applyRect(rect) {
    frame.style.top = rect.top + 'px';
    frame.style.left = rect.left + 'px';
    frame.style.width = rect.width + 'px';
    frame.style.height = rect.height + 'px';
  }

  function getCoverRect() {
    var rect = hero.getBoundingClientRect();
    var top = Math.max(0, rect.top);
    var left = Math.max(0, rect.left);
    var right = Math.min(window.innerWidth, rect.right);
    var bottom = Math.min(window.innerHeight, rect.bottom);
    return {
      top: top,
      left: left,
      width: Math.max(1, right - left),
      height: Math.max(1, bottom - top)
    };
  }

  function finishTransition(callback) {
    window.setTimeout(function() {
      isAnimating = false;
      if (callback) callback();
    }, transitionDuration + 40);
  }

  function expandVideo() {
    if (isExpanded || isAnimating) return;

    isAnimating = true;
    isExpanded = true;
    originRect = frame.getBoundingClientRect();
    applyRect(originRect);
    frame.style.position = 'fixed';
    frame.style.borderRadius = '0px';
    frame.classList.add('is-zoomed');
    hero.classList.add('has-expanded-video');
    document.body.classList.add('hero-video-overlay-open');
    expandButton.setAttribute('aria-expanded', 'true');

    frame.getBoundingClientRect();
    window.requestAnimationFrame(function() {
      applyRect(getCoverRect());
    });

    video.play().catch(function() {});
    finishTransition(function() {
      collapseButton.focus({preventScroll: true});
    });
  }

  function cleanCollapsedState() {
    frame.classList.remove('is-zoomed');
    frame.removeAttribute('style');
    hero.classList.remove('has-expanded-video');
    document.body.classList.remove('hero-video-overlay-open');
    expandButton.setAttribute('aria-expanded', 'false');
    originRect = null;
  }

  function collapseVideo() {
    if (!isExpanded || isAnimating) return;

    if (document.fullscreenElement) {
      document.exitFullscreen().then(collapseVideo).catch(function() {});
      return;
    }

    isAnimating = true;
    isExpanded = false;
    applyRect(originRect || video.getBoundingClientRect());

    finishTransition(function() {
      cleanCollapsedState();
      expandButton.focus({preventScroll: true});
    });
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      frame.requestFullscreen().catch(function() {});
    } else {
      document.exitFullscreen().catch(function() {});
    }
  }

  function updateFullscreenControl() {
    if (!fullscreenButton || !fullscreenIcon || !fullscreenLabel) return;
    var isFullscreen = document.fullscreenElement === frame;
    fullscreenIcon.className = isFullscreen ? 'fa-solid fa-compress' : 'fa-solid fa-expand';
    fullscreenLabel.textContent = isFullscreen ? 'Exit full screen' : 'Full screen';
    fullscreenButton.title = fullscreenLabel.textContent;
  }

  video.addEventListener('click', expandVideo);
  video.addEventListener('keydown', function(event) {
    if ((event.key === 'Enter' || event.key === ' ') && !isExpanded) {
      event.preventDefault();
      expandVideo();
    }
  });
  expandButton.addEventListener('click', expandVideo);
  collapseButton.addEventListener('click', collapseVideo);
  fullscreenButton.addEventListener('click', toggleFullscreen);
  document.addEventListener('fullscreenchange', updateFullscreenControl);
  document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape' && isExpanded && !document.fullscreenElement) {
      collapseVideo();
    }
  });
  window.addEventListener('resize', function() {
    if (isExpanded && !document.fullscreenElement) {
      applyRect(getCoverRect());
    }
  });
})();

//* ======================== Slide Show Control ===================== */
const slider = document.querySelector('.container .slider');
const [btnLeft, btnRight] = ['prev_btn', 'next_btn'].map(id => document.getElementById(id));
let interval;

// Set positions
const setPositions = () => {
    if (slider) {
        [...slider.children].forEach((item, i) => 
            item.style.left = `${(i-1) * 440}px`);
    }
};

// Initial setup
if (slider) {
    setPositions();
}

// Set transition speed
const setTransitionSpeed = (speed) => {
    if (slider) {
        [...slider.children].forEach(item => 
            item.style.transitionDuration = speed);
    }
};

// Slide functions
const next = (isAuto = false) => {
    if (slider) {
        setTransitionSpeed(isAuto ? '1.5s' : '0.2s');
        slider.appendChild(slider.firstElementChild); 
        setPositions();
    }
};

const prev = () => {
    if (slider) {
        setTransitionSpeed('0.2s');
        slider.prepend(slider.lastElementChild); 
        setPositions();
    }
};

// Auto slide
const startAuto = () => interval = interval || setInterval(() => next(true), 2000);
const stopAuto = () => { clearInterval(interval); interval = null; };

// Event listeners
if (btnRight) btnRight.addEventListener('click', () => next(false));
if (btnLeft) btnLeft.addEventListener('click', prev);

// Mouse hover controls
[slider, btnLeft, btnRight].forEach(el => {
    if (el) {
        el.addEventListener('mouseover', stopAuto);
        el.addEventListener('mouseout', startAuto);
    }
});

// Start auto slide
if (slider) startAuto();

//* ======================== Copy Button in Code ===================== */
// add copy button to code blocks
var codeBlocks = document.querySelectorAll('pre');
codeBlocks.forEach(function(pre) {
  console.log('Processing pre block');
  var button = document.createElement('button');
  button.className = 'code-copy-btn';
  button.innerHTML = '<i class="far fa-copy"></i><span class="copy-text"></span>';
  pre.appendChild(button);
  
  // Add click handler for copy functionality
  button.addEventListener('click', function(e) {
    e.preventDefault();
    
    // Get the code text from the code element
    var code = pre.querySelector('code');
    if (code) {
      var text = code.textContent;
      
      // Copy to clipboard
      navigator.clipboard.writeText(text).then(function() {
          // Add copied class to show text (kept for animation)
          button.classList.add('copied');
          // Change icon to check and show text
          var icon = button.querySelector('i');
          var span = button.querySelector('.copy-text');
          icon.className = 'fa-solid fa-check';
          if (span) span.textContent = 'Copied';

          // Reset icon, text and class after 2 seconds
          setTimeout(function() {
            icon.className = 'far fa-copy';
            if (span) span.textContent = '';
            button.classList.remove('copied');
          }, 2000);
      }).catch(function(err) {
        console.error('Failed to copy:', err);
      });
    }
  });
});
