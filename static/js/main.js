// ===== CSRF Helper =====
function getCookie(name) {
    let value = null;
    document.cookie.split(';').forEach(c => {
        c = c.trim();
        if (c.startsWith(name + '=')) value = decodeURIComponent(c.slice(name.length + 1));
    });
    return value;
}
const csrfToken = getCookie('csrftoken');

// ===== Live Clock =====
// Always shows Pakistan Standard Time from the server, NOT the device clock.
// We apply the server/device offset (set in base.html) so a wrong laptop clock
// or a different timezone still shows the correct PKT time.
const PKT_TZ = 'Asia/Karachi';

function serverNow() {
    const offset = (typeof window.__CLIENT_OFFSET_MS === 'number') ? window.__CLIENT_OFFSET_MS : 0;
    return new Date(Date.now() + offset);
}

function updateClock() {
    const now = serverNow();
    const timeEl = document.getElementById('liveClock');
    const dateEl = document.getElementById('liveDate');
    if (timeEl) {
        timeEl.textContent = now.toLocaleTimeString('en-US', { timeZone: PKT_TZ, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }
    if (dateEl) {
        dateEl.textContent = now.toLocaleDateString('en-US', { timeZone: PKT_TZ, weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
    }
}
setInterval(updateClock, 1000);
updateClock();

// ===== Sidebar Toggle =====
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('sidebar-overlay');
const toggleBtn = document.getElementById('sidebar-toggle');

function openSidebar() {
    sidebar?.classList.add('open');
    overlay?.classList.add('show');
}
function closeSidebar() {
    sidebar?.classList.remove('open');
    overlay?.classList.remove('show');
}

toggleBtn?.addEventListener('click', openSidebar);
overlay?.addEventListener('click', closeSidebar);

// ===== Check-In (also handles re-check-in after accidental checkout) =====
async function handleCheckIn() {
    const btn = document.getElementById('checkInBtn');
    if (!btn || btn.disabled) return;

    // Remember original label so we can restore on failure
    const originalHTML = btn.innerHTML;
    const isRecheckin = btn.classList.contains('att-recheckin-btn');

    btn.disabled = true;
    if (isRecheckin) {
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Please wait…';
    } else {
        btn.innerHTML = '<i class="fas fa-spinner fa-spin att-btn-icon"></i><span>Wait…</span>';
    }

    try {
        const res = await fetch('/attendance/check-in/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (data.success) {
            const msg = data.message && data.message.includes('again')
                ? 'Checked in again — checkout cleared.'
                : 'Checked in at ' + (data.time || data.check_in);
            showToast(msg, 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast(data.error || 'Check-in failed', 'error');
            btn.disabled = false;
            btn.innerHTML = originalHTML;
        }
    } catch (e) {
        showToast('Network error. Please try again.', 'error');
        btn.disabled = false;
        btn.innerHTML = originalHTML;
    }
}

// ===== Check-Out =====
async function handleCheckOut() {
    const btn = document.getElementById('checkOutBtn');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin att-btn-icon"></i><span>Wait…</span>';

    try {
        const res = await fetch('/attendance/check-out/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (data.success) {
            showToast('Checked out — ' + data.work_hours + 'h worked', 'success');
            setTimeout(() => location.reload(), 1000);
        } else {
            showToast(data.error || 'Check-out failed', 'error');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-sign-out-alt att-btn-icon"></i><span>Check Out</span>';
        }
    } catch (e) {
        showToast('Network error. Please try again.', 'error');
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-sign-out-alt att-btn-icon"></i><span>Check Out</span>';
    }
}

// ===== Toast Notification =====
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer') || createToastContainer();
    const toast = document.createElement('div');
    const bgColor = type === 'success' ? '#2ec4b6' : type === 'error' ? '#e63946' : '#4361ee';
    toast.style.cssText = `
        background: ${bgColor}; color: white; padding: 12px 20px; border-radius: 10px;
        margin-bottom: 8px; font-size: 0.875rem; font-weight: 500;
        box-shadow: 0 4px 20px rgba(0,0,0,0.2);
        animation: slideIn 0.3s ease; max-width: 320px;
        display: flex; align-items: center; gap: 8px;
    `;
    toast.innerHTML = `<i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i> ${message}`;
    container.appendChild(toast);
    setTimeout(() => { toast.style.animation = 'slideOut 0.3s ease'; setTimeout(() => toast.remove(), 300); }, 3000);
}

function createToastContainer() {
    const c = document.createElement('div');
    c.id = 'toastContainer';
    c.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 9999;';
    document.body.appendChild(c);
    return c;
}

const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    @keyframes slideOut { from { transform: translateX(0); opacity: 1; } to { transform: translateX(100%); opacity: 0; } }
`;
document.head.appendChild(style);

// ===== Mark Notification Read =====
async function markNotifRead(pk) {
    try {
        const res = await fetch(`/notifications/${pk}/read/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });
        const data = await res.json();
        if (data.success) {
            const el = document.getElementById(`notif-${pk}`);
            if (el) { el.classList.remove('unread'); el.querySelector('.unread-dot')?.remove(); }
            const badge = document.getElementById('notif-badge');
            if (badge) {
                const count = parseInt(badge.textContent) - 1;
                if (count <= 0) badge.style.display = 'none';
                else badge.textContent = count > 9 ? '9+' : count;
            }
        }
    } catch (e) {}
}

// ===== Mark All Notifications Read =====
async function markAllRead() {
    try {
        const res = await fetch('/notifications/mark-all-read/', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });
        const data = await res.json();
        if (data.success) {
            document.querySelectorAll('.notif-item.unread').forEach(el => {
                el.classList.remove('unread');
                el.querySelector('.unread-dot')?.remove();
            });
            const badge = document.getElementById('notif-badge');
            if (badge) badge.style.display = 'none';
            showToast('All notifications marked as read', 'success');
        }
    } catch (e) {}
}

// ===== Leave Duration Calculator =====
function calcLeaveDays() {
    const from = document.getElementById('id_from_date')?.value;
    const to = document.getElementById('id_to_date')?.value;
    const halfDay = document.getElementById('id_is_half_day')?.checked;
    const display = document.getElementById('leaveDaysDisplay');
    if (!display) return;
    if (halfDay) { display.textContent = '0.5 day'; return; }
    if (from && to) {
        const d1 = new Date(from), d2 = new Date(to);
        if (d2 >= d1) {
            let days = 0;
            let cur = new Date(d1);
            while (cur <= d2) {
                const day = cur.getDay();
                if (day !== 0 && day !== 6) days++;
                cur.setDate(cur.getDate() + 1);
            }
            display.textContent = days + (days === 1 ? ' working day' : ' working days');
        }
    }
}

document.getElementById('id_from_date')?.addEventListener('change', calcLeaveDays);
document.getElementById('id_to_date')?.addEventListener('change', calcLeaveDays);
document.getElementById('id_is_half_day')?.addEventListener('change', calcLeaveDays);

// ===== Auto-dismiss Alerts =====
document.querySelectorAll('.alert:not(.alert-permanent)').forEach(alert => {
    setTimeout(() => {
        alert.style.transition = 'opacity 0.5s';
        alert.style.opacity = '0';
        setTimeout(() => alert.remove(), 500);
    }, 4000);
});

// ===== Confirm Dangerous Actions =====
document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', function(e) {
        if (!confirm(this.dataset.confirm)) e.preventDefault();
    });
});

// ===== Active Sidebar Link =====
const currentPath = window.location.pathname;
document.querySelectorAll('.sidebar-nav .nav-link').forEach(link => {
    if (link.getAttribute('href') && currentPath.startsWith(link.getAttribute('href')) && link.getAttribute('href') !== '/') {
        link.classList.add('active');
    }
});
