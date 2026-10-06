const assert = require('node:assert/strict');
const test = require('node:test');
const { add } = require('../math');

test('addition', () => assert.equal(add(2, 3), 5));
