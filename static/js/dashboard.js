(() => {
  const zones = Array.isArray(window.RESQ_ZONES) ? window.RESQ_ZONES : [];
  const colors = { detected: '#d95f4c', uncertain: '#d6a23e', unsearched: '#98a39b', reviewed: '#4e986a', outdated: '#e58a45' };
  let map;
  if (window.L && document.getElementById('disasterMap') && zones.some((zone) => typeof zone.lat === 'number' && typeof zone.lng === 'number')) {
    const firstMappedZone = zones.find((zone) => typeof zone.lat === 'number' && typeof zone.lng === 'number');
    map = L.map('disasterMap', { scrollWheelZoom: false }).setView([firstMappedZone.lat, firstMappedZone.lng], 13);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
    zones.forEach((zone) => {
      if (typeof zone.lat !== 'number' || typeof zone.lng !== 'number') return;
      const marker = L.circleMarker([zone.lat, zone.lng], {
        radius: zone.key === 'detected' ? 9 : 7,
        color: '#ffffff', weight: 2, fillColor: colors[zone.key] || '#98a39b', fillOpacity: 0.95
      }).addTo(map);
      marker.bindPopup(`<div class="map-popup"><strong>${escapeHtml(zone.name)}</strong><span>${escapeHtml(zone.status)}</span><small>${escapeHtml(zone.note)}</small></div>`);
      marker.on('click', () => showZone(zone.name));
    });
  } else {
    const mapBox = document.getElementById('disasterMap');
    if (mapBox) mapBox.innerHTML = '<div class="map-offline">No zone coordinates are available yet. Add verified coordinates to zone records to display them on the map. The evidence register remains available below.</div>'; 
  }

  const filter = document.getElementById('statusFilter');
  const rows = [...document.querySelectorAll('#zoneTableBody tr')];
  const empty = document.getElementById('emptyFilter');
  if (filter) filter.addEventListener('change', () => {
    let visible = 0;
    rows.forEach((row) => {
      const show = filter.value === 'all' || row.dataset.status === filter.value;
      row.hidden = !show;
      if (show) visible++;
    });
    if (empty) empty.hidden = visible !== 0;
  });

  document.querySelectorAll('.inspect-btn').forEach((button) => button.addEventListener('click', () => showZone(button.dataset.zone)));
  const modal = document.getElementById('zoneModal');
  const closeButtons = [document.getElementById('closeModal'), document.getElementById('doneModal')];
  closeButtons.forEach((button) => button && button.addEventListener('click', closeModal));
  if (modal) modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(); });
  document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModal(); });

  function showZone(name) {
    const zone = zones.find((item) => item.name === name);
    if (!zone || !modal) return;
    document.getElementById('modalTitle').textContent = zone.name;
    document.getElementById('modalContent').innerHTML = [
      detail('Evidence status', zone.status),
      detail('Last observation', zone.time),
      detail('Area', zone.area),
      detail('Evidence note', zone.note),
      detail('Suggested next step', zone.action),
      detail('Recorded evidence', 'Details are based on the saved zone record.')
    ].join('');
    modal.hidden = false;
    document.getElementById('closeModal').focus();
  }
  function detail(label, value) { return `<div class="modal-detail"><strong>${escapeHtml(label)}</strong><span>${escapeHtml(value || 'Not available')}</span></div>`; }
  function closeModal() { if (modal) modal.hidden = true; }
  function escapeHtml(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char])); }
})();
