document.addEventListener('DOMContentLoaded', () => {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
      }
    });
  }, { threshold: 0.15 });

  document.querySelectorAll('.animate-fade-up, .fade-in').forEach((el) => {
    if (reducedMotion) {
      el.classList.add('is-visible');
      return;
    }
    observer.observe(el);
  });

  const themeToggle = document.querySelector('[data-theme-toggle]');
  if (themeToggle) {
    const saved = localStorage.getItem('logitrack-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const shouldDark = saved ? saved === 'dark' : prefersDark;
    document.documentElement.classList.toggle('dark', shouldDark);
    themeToggle.checked = shouldDark;
    themeToggle.addEventListener('change', () => {
      const next = themeToggle.checked ? 'dark' : 'light';
      document.documentElement.classList.toggle('dark', themeToggle.checked);
      localStorage.setItem('logitrack-theme', next);
    });
  }

  document.querySelectorAll('[data-copy-link]').forEach((button) => {
    button.addEventListener('click', async () => {
      const url = button.dataset.copyLink;
      try {
        await navigator.clipboard.writeText(url);
        const icon = button.querySelector('[data-copy-icon]');
        const done = button.querySelector('[data-copy-done]');
        if (icon) icon.classList.add('hidden');
        if (done) done.classList.remove('hidden');
        setTimeout(() => {
          if (icon) icon.classList.remove('hidden');
          if (done) done.classList.add('hidden');
        }, 1200);
      } catch (error) {
        console.error('Copy failed', error);
      }
    });
  });

  document.querySelectorAll('[data-dismiss-toast]').forEach((button) => {
    button.addEventListener('click', () => button.closest('[data-toast]')?.remove());
  });
  document.querySelectorAll('[data-toast]').forEach((toast) => {
    window.setTimeout(() => {
      toast.classList.add('toast-dismiss');
      window.setTimeout(() => toast.remove(), 250);
    }, 5000);
  });

  document.querySelectorAll('[data-copy-text]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copyText);
        const originalLabel = button.dataset.copyLabel || button.textContent;
        button.textContent = '✓';
        window.setTimeout(() => { button.textContent = originalLabel; }, 1200);
      } catch (error) {
        console.error('Copy failed', error);
      }
    });
  });

  document.querySelectorAll('[data-scroll-fade]').forEach((wrapper) => {
    const scroller = wrapper.querySelector('nav');
    if (!scroller) return;
    const updateOverflow = () => {
      wrapper.dataset.overflow = String(scroller.scrollWidth > scroller.clientWidth + 1);
    };
    updateOverflow();
    scroller.addEventListener('scroll', updateOverflow, { passive: true });
    window.addEventListener('resize', updateOverflow);
  });

  document.querySelectorAll('header details nav a[href^="#"]').forEach((link) => {
    link.addEventListener('click', () => {
      const menu = link.closest('details');
      if (menu) menu.open = false;
    });
  });

  const consignmentForm = document.querySelector('[data-consignment-preview]');
  if (consignmentForm) {
    const preview = (fieldName, target, fallback, format = (value) => value) => {
      const field = consignmentForm.elements.namedItem(fieldName);
      const output = consignmentForm.querySelector(`[data-preview-${target}]`);
      if (!field || !output) return;
      const update = () => {
        const value = field.value.trim();
        output.textContent = value ? format(value) : fallback;
      };
      field.addEventListener('input', update);
      field.addEventListener('change', update);
      update();
    };
    preview('recipient_name', 'recipient', 'Not specified');
    preview('origin', 'origin', 'Origin hub');
    preview('destination', 'destination', 'Destination');
    preview('carrier', 'carrier', 'Select carrier');
    preview('estimated_delivery', 'eta', 'Not scheduled', (value) => value.replace('T', ' '));
    consignmentForm.addEventListener('keydown', (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault();
        consignmentForm.requestSubmit();
      }
    });
  }

  const liveFilter = document.querySelector('[data-live-filter]');
  const liveSearch = document.querySelector('[data-live-search]');
  if (liveFilter && liveSearch) {
    let searchTimeout;
    liveSearch.addEventListener('input', () => {
      window.clearTimeout(searchTimeout);
      searchTimeout = window.setTimeout(() => liveFilter.requestSubmit(), 300);
    });
    liveFilter.querySelectorAll('[data-submit-filter]').forEach((select) => {
      select.addEventListener('change', () => liveFilter.requestSubmit());
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === '/' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
        event.preventDefault();
        liveSearch.focus();
      }
    });
  }

  if (document.querySelector('#dashboard-range')) {
    document.addEventListener('keydown', (event) => {
      if (event.key.toLowerCase() === 'n' && !['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName)) {
        window.location.assign('/shipments/new/');
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        window.location.assign('/shipments/');
      }
    });
  }

  const trackingInput = document.querySelector('#tracking-number');
  const pasteButton = document.querySelector('[data-paste-tracking]');
  const pasteFeedback = document.querySelector('[data-paste-feedback]');
  const trackingForm = document.querySelector('[data-tracking-form]');
  const carrierBadge = document.querySelector('[data-carrier-badge]');

  const detectCarrier = (value) => {
    const code = value.trim().toUpperCase().replace(/\s+/g, '');
    if (!code) return 'AUTO CARRIER';
    if (/^(LT|LGT)[-A-Z0-9]/.test(code)) return 'LOGITRACK EXPRESS';
    if (/^DHL[-A-Z0-9]/.test(code)) return 'DHL';
    if (/^FDX[-A-Z0-9]/.test(code) || /^\d{12,22}$/.test(code)) return 'FEDEX';
    if (/^1Z[A-Z0-9]{6,}$/.test(code)) return 'UPS';
    if (/^(JD|JJD)[A-Z0-9]/.test(code)) return 'JD / OTHER';
    return 'AUTO CARRIER';
  };

  if (trackingInput && carrierBadge) {
    const updateCarrier = () => {
      carrierBadge.textContent = detectCarrier(trackingInput.value);
      carrierBadge.classList.toggle('tracking-carrier-known', carrierBadge.textContent !== 'AUTO CARRIER');
    };
    updateCarrier();
    trackingInput.addEventListener('input', updateCarrier);
  }

  if (trackingInput && pasteButton) {
    pasteButton.addEventListener('click', async () => {
      if (!navigator.clipboard || !navigator.clipboard.readText) {
        if (pasteFeedback) pasteFeedback.textContent = 'Clipboard access is not available in this browser.';
        return;
      }

      try {
        const value = (await navigator.clipboard.readText()).trim();
        if (value) {
          trackingInput.value = value;
          trackingInput.dispatchEvent(new Event('input', { bubbles: true }));
          trackingInput.focus();
          if (pasteFeedback) pasteFeedback.textContent = 'Tracking number pasted from clipboard.';
        } else if (pasteFeedback) {
          pasteFeedback.textContent = 'The clipboard is empty.';
        }
      } catch (error) {
        if (pasteFeedback) pasteFeedback.textContent = 'Clipboard access was denied. Paste your tracking number into the field.';
      }
    });

    document.addEventListener('keydown', (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        trackingInput.focus();
      }
    });
  }

  if (trackingInput && trackingForm) {
    document.querySelectorAll('[data-sample-tracking]').forEach((button) => {
      button.addEventListener('click', () => {
        trackingInput.value = button.dataset.sampleTracking;
        trackingInput.dispatchEvent(new Event('input', { bubbles: true }));
        trackingForm.requestSubmit();
      });
    });
  }

  document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    const passwordField = document.getElementById(button.dataset.passwordToggle);
    if (!passwordField) return;

    button.addEventListener('click', () => {
      const reveal = passwordField.type === 'password';
      passwordField.type = reveal ? 'text' : 'password';
      button.setAttribute('aria-pressed', String(reveal));
      button.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
      const icon = button.querySelector('[data-eye-icon]');
      if (icon) {
        icon.innerHTML = reveal
          ? '<path d="m3 3 18 18M10.6 10.6a2 2 0 0 0 2.8 2.8"/><path d="M9.9 5.2A10.8 10.8 0 0 1 12 5c6.4 0 10 7 10 7a16 16 0 0 1-3.1 3.7M6.2 6.2C3.5 8 2 12 2 12s3.6 7 10 7a10 10 0 0 0 4-.8"/>'
          : '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>';
      }
    });
  });

  const strengthInput = document.querySelector('[data-strength-password]');
  if (strengthInput) {
    const bars = [...document.querySelectorAll('[data-strength-bar]')];
    const label = document.querySelector('[data-strength-label]');
    const checks = {
      length: (value) => value.length >= 8,
      number: (value) => /\d/.test(value),
      symbol: (value) => /[^A-Za-z0-9]/.test(value),
    };

    strengthInput.addEventListener('input', () => {
      const value = strengthInput.value;
      const criteria = Object.fromEntries(
        Object.entries(checks).map(([name, test]) => [name, test(value)])
      );
      const score = Object.values(criteria).filter(Boolean).length
        + Number(value.length >= 12 && /[A-Z]/.test(value));
      const strength = score === 0 ? 'Password strength' : score <= 1 ? 'Weak' : score <= 2 ? 'Fair' : score === 3 ? 'Good' : 'Strong';
      const color = score <= 1 ? 'bg-rose-500' : score <= 2 ? 'bg-amber-500' : 'bg-emerald-500';

      bars.forEach((bar, index) => {
        bar.classList.remove('bg-zinc-200', 'bg-rose-500', 'bg-amber-500', 'bg-emerald-500');
        bar.classList.add(index < score ? color : 'bg-zinc-200');
      });
      if (label) {
        label.textContent = strength;
        label.classList.toggle('text-rose-600', score <= 1 && score > 0);
        label.classList.toggle('text-amber-600', score === 2);
        label.classList.toggle('text-emerald-700', score >= 3);
        label.classList.toggle('text-zinc-400', score === 0);
      }
      Object.entries(criteria).forEach(([name, passed]) => {
        const item = document.querySelector(`[data-password-check="${name}"]`);
        if (item) {
          item.classList.toggle('text-emerald-700', passed);
          item.classList.toggle('text-zinc-400', !passed);
          item.setAttribute('aria-label', `${name}: ${passed ? 'met' : 'not met'}`);
        }
      });
    });
  }

  document.querySelectorAll('[data-auth-form]').forEach((form) => {
    form.addEventListener('submit', () => {
      const button = form.querySelector('[data-auth-submit]');
      if (!button || !form.reportValidity()) return;
      button.disabled = true;
      button.setAttribute('aria-busy', 'true');
      button.dataset.originalLabel = button.textContent.trim();
      button.innerHTML = '<span class="auth-spinner" aria-hidden="true"></span> Please wait…';
    });
  });

  const etaClock = document.querySelector('[data-eta-clock]');
  if (etaClock) {
    const updateEta = () => {
      const now = new Date();
      let target = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 23, 20);
      if (target <= now.getTime()) target += 24 * 60 * 60 * 1000;
      const remaining = Math.floor((target - now.getTime()) / 1000);
      const hours = String(Math.floor(remaining / 3600)).padStart(2, '0');
      const minutes = String(Math.floor((remaining % 3600) / 60)).padStart(2, '0');
      const seconds = String(remaining % 60).padStart(2, '0');
      etaClock.textContent = `ETA 16:20 MST · ${hours}:${minutes}:${seconds}`;
    };
    updateEta();
    window.setInterval(updateEta, 1000);
  }

  const syncClock = document.querySelector('[data-sync-clock]');
  if (syncClock) {
    const updateSync = () => {
      syncClock.textContent = new Intl.DateTimeFormat('en-GB', {
        timeZone: 'UTC',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }).format(new Date());
    };
    updateSync();
    window.setInterval(updateSync, 1000);
  }
});
