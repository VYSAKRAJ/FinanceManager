/* ============================================================
   CardIQ – App JavaScript
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {

  // ── Sidebar toggle ────────────────────────────────────────
  const toggleBtn = document.getElementById('sidebarToggle');
  const sidebar   = document.getElementById('sidebar');

  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', () => {
      sidebar.classList.toggle('open');
    });

    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', (e) => {
      if (window.innerWidth < 769 &&
          !sidebar.contains(e.target) &&
          !toggleBtn.contains(e.target)) {
        sidebar.classList.remove('open');
      }
    });
  }

  // ── Notification badge ────────────────────────────────────
  checkUpcomingPayments();

  // ── Auto-dismiss alerts after 5 s ─────────────────────────
  document.querySelectorAll('.alert.alert-success').forEach(el => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      if (bsAlert) bsAlert.close();
    }, 5000);
  });

  // ── Confirm delete forms ──────────────────────────────────
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('submit', (e) => {
      if (!confirm(el.dataset.confirm)) e.preventDefault();
    });
  });

  // ── Number formatting in display ─────────────────────────
  document.querySelectorAll('[data-rupee]').forEach(el => {
    const val = parseFloat(el.dataset.rupee);
    if (!isNaN(val)) {
      el.textContent = '₹' + val.toLocaleString('en-IN', {
        maximumFractionDigits: 2,
        minimumFractionDigits: 0
      });
    }
  });

});

/* Check upcoming payments and update notification badge */
async function checkUpcomingPayments() {
  const badge = document.getElementById('notif-badge');
  if (!badge) return;

  try {
    const resp = await fetch('/api/upcoming-payments');
    if (!resp.ok) return;
    const payments = await resp.json();
    const urgent = payments.filter(p => p.days_until_due <= 7);
    if (urgent.length > 0) {
      badge.textContent = urgent.length;
      badge.style.display = 'flex';
      badge.style.alignItems = 'center';
      badge.style.justifyContent = 'center';
      badge.style.width = '16px';
      badge.style.height = '16px';
      badge.style.borderRadius = '50%';
      badge.style.background = '#ef4444';
      badge.style.color = '#fff';
      badge.style.fontSize = '9px';
      badge.style.fontWeight = 'bold';
    }
  } catch (_) { /* silently ignore */ }
}

/* Utility: format currency */
function formatRupee(amount) {
  return '₹' + parseFloat(amount).toLocaleString('en-IN', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0
  });
}

/* Utility: format date as DD Mon YYYY */
function formatDate(dateStr) {
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric'
  });
}

/* Schedule browser notification for a due date */
function scheduleNotification(title, body, delayMs) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  if (delayMs <= 0) {
    new Notification(title, { body });
  } else {
    setTimeout(() => new Notification(title, { body }), delayMs);
  }
}

/* Download data as CSV */
function exportTableToCSV(tableId, filename) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const rows = Array.from(table.querySelectorAll('tr'));
  const csv  = rows.map(row =>
    Array.from(row.querySelectorAll('th,td'))
         .map(cell => `"${cell.innerText.replace(/"/g, '""')}"`)
         .join(',')
  ).join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
