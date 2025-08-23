async function loadReleases() {
  const resp = await fetch('results/index.json');
  const releases = await resp.json();
  const sel = document.getElementById('release');
  releases.forEach(r => {
    const opt = document.createElement('option');
    opt.value = r;
    opt.textContent = r;
    sel.appendChild(opt);
  });
  if (releases.length) {
    sel.value = releases[0];
    await showRelease(releases[0]);
  }
  sel.addEventListener('change', () => showRelease(sel.value));
}

async function showRelease(release) {
  const resp = await fetch(`results/${release}.json`);
  const data = await resp.json();
  const tbody = document.querySelector('#results tbody');
  tbody.innerHTML = '';
  data.examples.forEach(ex => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${ex.prompt}</td><td>${ex.expected}</td><td>${ex.answer}</td><td>${ex.correct}</td>`;
    tbody.appendChild(tr);
  });
}

loadReleases();
