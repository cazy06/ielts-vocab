const INDEX_RE = /^\/(?:index\.html)?$/;

function json(data, init = {}) {
  return new Response(JSON.stringify(data), {
    ...init,
    headers: {
      'content-type': 'application/json; charset=utf-8',
      'cache-control': 'no-store',
      ...(init.headers || {}),
    },
  });
}

function getUserEmail(request) {
  return request.headers.get('cf-access-authenticated-user-email') || '';
}

function userKey(email) {
  return `vocab:${email.toLowerCase()}`;
}

async function readBody(request) {
  const body = await request.json();
  if (!body || typeof body !== 'object' || !body.state || typeof body.state !== 'object') {
    throw new Error('Invalid state payload');
  }
  const state = body.state;
  return {
    progress: state.progress && typeof state.progress === 'object' ? state.progress : {},
    marked: state.marked && typeof state.marked === 'object' ? state.marked : {},
    custom: Array.isArray(state.custom) ? state.custom : [],
    dailyDate: typeof state.dailyDate === 'string' ? state.dailyDate : '',
    dailyCount: Number.isFinite(Number(state.dailyCount)) ? Number(state.dailyCount) : 0,
    cloudUpdatedAt: new Date().toISOString(),
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/api/vocab-state') {
      const email = getUserEmail(request);
      if (!email) {
        return json({ authenticated: false, error: 'Cloudflare Access login is required.' }, { status: 401 });
      }

      if (request.method === 'GET') {
        const state = await env.IELTS_VOCAB_STATE.get(userKey(email), 'json');
        return json({ authenticated: true, email, state: state || null });
      }

      if (request.method === 'POST') {
        try {
          const state = await readBody(request);
          await env.IELTS_VOCAB_STATE.put(userKey(email), JSON.stringify(state));
          return json({ authenticated: true, email, state });
        } catch (error) {
          return json({ authenticated: true, email, error: error.message }, { status: 400 });
        }
      }

      return json({ error: 'Method not allowed' }, { status: 405, headers: { allow: 'GET, POST' } });
    }

    if (INDEX_RE.test(url.pathname)) {
      return env.ASSETS.fetch(request);
    }

    return env.ASSETS.fetch(request);
  },
};
