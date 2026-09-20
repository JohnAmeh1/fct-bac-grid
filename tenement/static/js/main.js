/* ============================================================
   BWARI TENEMENT RATE SYSTEM — main.js
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

  /* ---- NAVBAR SCROLL SHADOW ---- */
  const navbar = document.getElementById('navbar');
  if (navbar) {
    window.addEventListener('scroll', () => {
      if (window.scrollY > 10) {
        navbar.style.boxShadow = '0 4px 24px rgba(0,0,0,.1)';
      } else {
        navbar.style.boxShadow = '0 1px 3px rgba(0,0,0,.08)';
      }
    }, { passive: true });
  }

  /* ---- HAMBURGER MENU ---- */
  const hamburger = document.getElementById('hamburger');
  const mobileDrawer = document.getElementById('mobileDrawer');

  if (hamburger && mobileDrawer) {
    hamburger.addEventListener('click', () => {
      const isOpen = mobileDrawer.classList.toggle('open');
      hamburger.classList.toggle('open', isOpen);
      hamburger.setAttribute('aria-expanded', isOpen);
      document.body.style.overflow = isOpen ? 'hidden' : '';
    });

    // Close drawer on backdrop click (outside the nav)
    document.addEventListener('click', (e) => {
      if (!navbar.contains(e.target) && mobileDrawer.classList.contains('open')) {
        mobileDrawer.classList.remove('open');
        hamburger.classList.remove('open');
        hamburger.setAttribute('aria-expanded', false);
        document.body.style.overflow = '';
      }
    });

    // Close on ESC
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && mobileDrawer.classList.contains('open')) {
        mobileDrawer.classList.remove('open');
        hamburger.classList.remove('open');
        hamburger.setAttribute('aria-expanded', false);
        document.body.style.overflow = '';
      }
    });
  }

  /* ---- STATS COUNTER ANIMATION ---- */
  function formatShort(n) {
    if (n >= 1000000000) return '₦' + (n / 1000000000).toFixed(1) + 'B';
    if (n >= 1000000)    return '₦' + (n / 1000000).toFixed(0) + 'M';
    if (n >= 1000)       return n.toLocaleString();
    return n.toString();
  }

  function animateCounter(el) {
    const target = parseInt(el.dataset.target, 10);
    const isShort = el.dataset.short === 'true';
    const duration = 2000;
    const start = performance.now();

    function update(now) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(eased * target);
      el.textContent = isShort ? formatShort(current) : current.toLocaleString();
      if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
  }

  // Intersection Observer to trigger counters when visible
  const statEls = document.querySelectorAll('.stat-num[data-target]');
  if (statEls.length) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    statEls.forEach(el => observer.observe(el));
  }

  /* ---- DESKTOP DROPDOWN CLICK TOGGLE ---- */
  const desktopDropdownTriggers = document.querySelectorAll('.nav-links .has-dropdown > .dropdown-toggle');

  function closeAllDesktopDropdowns(except) {
    document.querySelectorAll('.nav-links .has-dropdown').forEach(item => {
      if (item !== except) {
        item.classList.remove('open');
        const icon = item.querySelector('.dropdown-toggle .fa-chevron-down');
        if (icon) icon.style.transform = '';
      }
    });
  }

  desktopDropdownTriggers.forEach(trigger => {
    trigger.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const parent = trigger.closest('.has-dropdown');
      const isOpen = parent.classList.contains('open');
      closeAllDesktopDropdowns(parent);
      parent.classList.toggle('open', !isOpen);
      const icon = trigger.querySelector('.fa-chevron-down');
      if (icon) icon.style.transform = parent.classList.contains('open') ? 'rotate(180deg)' : '';
    });
  });

  // Close desktop dropdowns when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.nav-links .has-dropdown')) {
      closeAllDesktopDropdowns(null);
    }
  });

  // Close desktop dropdowns on ESC
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeAllDesktopDropdowns(null);
  });

  /* ---- SMOOTH ANCHOR SCROLL ---- */
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', (e) => {
      const target = document.querySelector(anchor.getAttribute('href'));
      if (target) {
        e.preventDefault();
        const navH = (navbar ? navbar.offsetHeight : 72) + 40;
        const top = target.getBoundingClientRect().top + window.scrollY - navH;
        window.scrollTo({ top, behavior: 'smooth' });

        // Close mobile drawer if open
        if (mobileDrawer && mobileDrawer.classList.contains('open')) {
          mobileDrawer.classList.remove('open');
          hamburger.classList.remove('open');
          document.body.style.overflow = '';
        }
      }
    });
  });

  /* ---- ALERT AUTO-DISMISS ---- */
  document.querySelectorAll('.alert').forEach(alert => {
    setTimeout(() => {
      alert.style.opacity = '0';
      alert.style.transition = 'opacity 0.4s ease';
      setTimeout(() => alert.remove(), 400);
    }, 5000);
  });

  /* ---- SCROLL REVEAL (lightweight) ---- */
  const revealEls = document.querySelectorAll(
    '.step-card, .feature-card, .usertype-card, .mockup-card'
  );

  if (revealEls.length) {
    const revealObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          entry.target.style.animationDelay = `${i * 0.07}s`;
          entry.target.classList.add('revealed');
          revealObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });

    revealEls.forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(20px)';
      el.style.transition = 'opacity 0.5s ease, transform 0.5s ease';
      revealObserver.observe(el);
    });
  }

});