async function send(url, method, body) {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function getJson(url) {
  return send(url, 'GET')
}

export async function postJson(url, body) {
  return send(url, 'POST', body)
}

export async function putJson(url, body) {
  return send(url, 'PUT', body)
}

export async function deleteJson(url) {
  return send(url, 'DELETE')
}
