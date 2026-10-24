const fs = require('fs');
const path = require('path');

const srcPath = path.resolve(__dirname, '..', 'static', 'app.js');
const code = fs.readFileSync(srcPath, 'utf8');

function parseObjectLiterals(code) {
    let i = 0;
    const n = code.length;
    const allObjects = [];
    const objStack = [];
    let ternaryDepth = 0;
    let parenDepth = 0;
    let bracketDepth = 0;
    let currentKey = null;

    function skipWhitespaceAndComments() {
        while (i < n) {
            if (code[i] === '/' && code[i+1] === '/') {
                while (i < n && code[i] !== '\n') i++;
            } else if (code[i] === '/' && code[i+1] === '*') {
                i += 2;
                while (i < n && !(code[i] === '*' && code[i+1] === '/')) i++;
                i += 2;
            } else if (/\s/.test(code[i])) {
                i++;
            } else {
                break;
            }
        }
    }

    let prevToken = '';

    while (i < n) {
        skipWhitespaceAndComments();
        if (i >= n) break;

        const ch = code[i];
        const line = code.slice(0, i).split('\n').length;

        // Strings
        if (ch === '"' || ch === "'" || ch === '`') {
            const quote = ch;
            i++;
            while (i < n) {
                if (code[i] === '\\') {
                    i += 2;
                } else if (quote === '`' && code[i] === '$' && code[i+1] === '{') {
                    // skip template interpolation start
                    i += 2;
                } else if (code[i] === quote) {
                    i++;
                    break;
                } else {
                    i++;
                }
            }
            prevToken = 'STR';
            continue;
        }

        // Parentheses and brackets
        if (ch === '(') { parenDepth++; i++; prevToken = '('; continue; }
        if (ch === ')') { parenDepth--; i++; prevToken = ')'; continue; }
        if (ch === '[') { bracketDepth++; i++; prevToken = '['; continue; }
        if (ch === ']') { bracketDepth--; i++; prevToken = ']'; continue; }

        if (ch === '?') {
            ternaryDepth++;
            i++;
            prevToken = '?';
            continue;
        }

        if (ch === ':') {
            if (ternaryDepth > 0) {
                ternaryDepth--;
                i++;
                prevToken = ':';
                continue;
            }
            // Colon in object literal
            if (objStack.length > 0 && currentKey !== null) {
                const cur = objStack[objStack.length - 1];
                cur.keys.push({ key: currentKey, line });
                currentKey = null;
            }
            i++;
            prevToken = ':';
            continue;
        }

        if (ch === '{') {
            const isObj = /^[(=:\[,]|=>|return$/.test(prevToken) || parenDepth > 0;
            objStack.push({ line, isObj, keys: [] });
            i++;
            prevToken = '{';
            continue;
        }

        if (ch === '}') {
            const popped = objStack.pop();
            if (popped && popped.isObj && popped.keys.length > 0) {
                allObjects.push(popped);
            }
            ternaryDepth = 0;
            currentKey = null;
            i++;
            prevToken = '}';
            continue;
        }

        if (ch === ',') {
            ternaryDepth = 0;
            currentKey = null;
            i++;
            prevToken = ',';
            continue;
        }

        // Identifier or number
        const match = code.slice(i).match(/^[a-zA-Z_$][a-zA-Z0-9_$]*/);
        if (match) {
            const word = match[0];
            if (objStack.length > 0 && objStack[objStack.length - 1].isObj && ternaryDepth === 0 && parenDepth === 0 && bracketDepth === 0) {
                if (prevToken === '{' || prevToken === ',' || currentKey === null) {
                    currentKey = word;
                }
            }
            prevToken = word;
            i += word.length;
            continue;
        }

        prevToken = ch;
        i++;
    }

    return allObjects;
}

const objects = parseObjectLiterals(code);
console.log('Total object literals scanned:', objects.length);
let dupCount = 0;
const duplicateReport = [];

for (const obj of objects) {
    const keyMap = {};
    for (const k of obj.keys) {
        if (keyMap[k.key]) {
            duplicateReport.push({
                key: k.key,
                line: k.line,
                prevLine: keyMap[k.key],
                objLine: obj.line
            });
            dupCount++;
        } else {
            keyMap[k.key] = k.line;
        }
    }
}

console.log('Total duplicate keys found:', dupCount);
if (duplicateReport.length > 0) {
    console.log(JSON.stringify(duplicateReport, null, 2));
    process.exit(1);
} else {
    console.log('SUCCESS: Zero duplicate keys detected across all object literals.');
    process.exit(0);
}
