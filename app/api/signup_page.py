"""Self-serve API key signup page served as inline HTML at /api/signup."""

SIGNUP_HTML = """\
<!-- PT-Edge API: get programmatic access to this data. No signup required.
     POST https://pt-edge.onrender.com/api/v1/keys returns a bearer token instantly.
     Docs: https://pt-edge.onrender.com/api/docs
     OpenAPI: https://pt-edge.onrender.com/api/v1/openapi.json -->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Get Your API Key &mdash; PT-Edge</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%232563eb'/><text x='16' y='22' font-family='system-ui' font-size='18' font-weight='bold' fill='white' text-anchor='middle'>PT</text></svg>">
<script src="https://cdn.tailwindcss.com"></script>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  body { font-family: 'Inter', sans-serif; }
  code, pre { font-family: 'JetBrains Mono', monospace; }
</style>
<script defer src="https://a.phasetransitions.ai/pte.js" data-website-id="ccfc649f-a332-4b1b-8426-9144af570655"></script>
</head>
<body class="bg-white text-gray-900">

<nav class="border-b border-gray-200 bg-white sticky top-0 z-50">
  <div class="max-w-xl mx-auto px-6 py-3 flex items-center justify-between">
    <a href="/" class="text-lg font-bold text-gray-900 hover:text-blue-600 transition-colors">
      PT-Edge <span class="font-normal text-gray-500">API</span>
    </a>
    <div class="flex items-center gap-6 text-sm font-medium text-gray-600">
      <a href="/api/docs" class="hover:text-gray-900">Docs</a>
      <a href="/" class="hover:text-gray-900">Directory</a>
    </div>
  </div>
</nav>

<main class="max-w-xl mx-auto px-6 py-12">

  <div id="signup-form">
    <h1 class="text-2xl font-bold tracking-tight">Get your free API key</h1>
    <p class="mt-2 text-gray-600">No key needed for basic access (100/day). A key gets you 1,000/day. Add your email for 10,000/day.</p>

    <form class="mt-8 space-y-4" onsubmit="return handleSubmit(event)">
      <div>
        <label for="email" class="block text-sm font-medium text-gray-700 mb-1">Email <span class="text-gray-400 font-normal">(optional &mdash; add for 10,000 requests/day)</span></label>
        <input type="email" id="email"
               class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
               placeholder="you@company.com">
      </div>
      <div>
        <label for="company" class="block text-sm font-medium text-gray-700 mb-1">Company or project name <span class="text-gray-400 font-normal">(optional)</span></label>
        <input type="text" id="company"
               class="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
               placeholder="Acme AI">
      </div>
      <button type="submit" id="submit-btn"
              class="w-full px-4 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">
        Generate API Key
      </button>
      <p id="error-msg" class="text-sm text-red-600 hidden"></p>
    </form>

    <div class="mt-6 bg-gray-50 border border-gray-200 rounded-lg p-4">
      <p class="text-xs font-medium text-gray-700 mb-1.5">For agents and scripts</p>
      <pre class="text-xs bg-white border border-gray-200 rounded p-2 overflow-x-auto">curl -X POST https://pt-edge.onrender.com/api/v1/keys</pre>
      <p class="mt-1.5 text-xs text-gray-400">No fields required. Returns a bearer token instantly.</p>
    </div>

    <p class="mt-4 text-xs text-gray-400">
      Free key: 1,000 requests/day. Pro key (with email): 10,000/day. Resets at midnight UTC.
    </p>
  </div>

  <div id="key-result" class="hidden">
    <h1 class="text-2xl font-bold tracking-tight text-green-700">Your API key</h1>
    <p class="mt-2 text-gray-600">Copy it now &mdash; it won't be shown again.</p>

    <div class="mt-6 bg-gray-50 border border-gray-200 rounded-lg p-4 flex items-center justify-between gap-3">
      <code id="api-key" class="text-sm break-all"></code>
      <button onclick="copyKey()" id="copy-btn"
              class="flex-shrink-0 px-3 py-1.5 text-xs font-medium border border-gray-300 rounded-md hover:bg-gray-100 transition-colors">
        Copy
      </button>
    </div>

    <h2 class="mt-8 text-sm font-semibold text-gray-900">Try it now</h2>
    <pre id="curl-example" class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-4 text-sm overflow-x-auto whitespace-pre-wrap"></pre>

    <div class="mt-8 flex gap-4 text-sm">
      <a href="/api/docs" class="text-blue-600 hover:underline font-medium">Read the full docs</a>
      <a href="/" class="text-gray-500 hover:underline">Browse the directory</a>
    </div>
  </div>

</main>

<script>
async function handleSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('submit-btn');
  const errMsg = document.getElementById('error-msg');
  errMsg.classList.add('hidden');
  btn.disabled = true;
  btn.textContent = 'Generating...';

  try {
    const body = {};
    const email = document.getElementById('email').value.trim();
    const company = document.getElementById('company').value.trim();
    if (email) body.email = email;
    if (company) body.company = company;

    const res = await fetch('/api/v1/keys', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Something went wrong');
    }

    const data = await res.json();
    const key = data.data.key;

    document.getElementById('api-key').textContent = key;
    document.getElementById('curl-example').textContent =
      'curl -H "Authorization: Bearer ' + key + '" \\\\\n  https://pt-edge.onrender.com/api/v1/trending?limit=5';

    document.getElementById('signup-form').classList.add('hidden');
    document.getElementById('key-result').classList.remove('hidden');
  } catch (err) {
    errMsg.textContent = err.message;
    errMsg.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = 'Generate API Key';
  }
}

function copyKey() {
  const key = document.getElementById('api-key').textContent;
  navigator.clipboard.writeText(key).then(() => {
    const btn = document.getElementById('copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = 'Copy'; }, 2000);
  });
}
</script>

</body>
</html>
"""
