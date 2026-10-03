// Baseline traffic for the orders API: a constant arrival rate that mixes
// writes and reads, with a share of orders created without a note (the field
// the v1.1.0 release mishandles, incident #1).
import http from 'k6/http';

const TARGET = __ENV.TARGET || 'http://orders:8000';
const RATE = parseInt(__ENV.RATE || '10', 10);
const NULL_NOTE_SHARE = parseFloat(__ENV.NULL_NOTE_SHARE || '0.3');

export const options = {
  scenarios: {
    baseline: {
      executor: 'constant-arrival-rate',
      rate: RATE,
      timeUnit: '1s',
      duration: '8760h', // runs until the pod is replaced
      preAllocatedVUs: 20,
      maxVUs: 100,
    },
  },
  discardResponseBodies: false,
  // No `url` tag: order IDs in URLs would explode metric cardinality.
  systemTags: ['status', 'method', 'name', 'expected_response', 'scenario'],
};

// Fail fast: a request to a dead node must count as a failure in seconds,
// not hang for the default 60 s.
const PARAMS = { timeout: '2s' };

const recentIds = [];

function createOrder() {
  const body = {
    customer_id: `c-${Math.floor(Math.random() * 500)}`,
    items: [{ sku: `sku-${Math.floor(Math.random() * 50)}`, qty: 1 + Math.floor(Math.random() * 3) }],
    note: Math.random() < NULL_NOTE_SHARE ? null : 'leave at the door',
  };
  const res = http.post(`${TARGET}/orders`, JSON.stringify(body), {
    ...PARAMS,
    headers: { 'Content-Type': 'application/json' },
    tags: { name: 'POST /orders' },
  });
  if (res.status === 201) {
    recentIds.push(res.json('id'));
    if (recentIds.length > 200) recentIds.shift();
  }
}

export default function () {
  const roll = Math.random();
  if (roll < 0.3 || recentIds.length === 0) {
    createOrder();
  } else if (roll < 0.85) {
    const id = recentIds[Math.floor(Math.random() * recentIds.length)];
    http.get(`${TARGET}/orders/${id}`, { ...PARAMS, tags: { name: 'GET /orders/{id}' } });
  } else {
    http.get(`${TARGET}/orders?limit=20`, { ...PARAMS, tags: { name: 'GET /orders' } });
  }
}
