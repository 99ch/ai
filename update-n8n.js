const fs = require('fs');

const path = '/Users/chilavert/Downloads/js-job pipeline.json';
const data = JSON.parse(fs.readFileSync(path, 'utf8'));

const fetchNode = data.nodes.find((node) => node.name === 'Fetch All CVs');
const normNode = data.nodes.find((node) => node.name === 'Normalize Job + CV');

if (!fetchNode || !normNode) {
  throw new Error('Nodes not found');
}

let fetchCode = fetchNode.parameters.jsCode;
const fetchSources = /const sources = \[\s*cv\.resume,\s*cv\.skills,\s*cv\.keywords,\s*cv\.text_content,\s*cv\.description,\s*\];/m;
fetchCode = fetchCode.replace(
  fetchSources,
  'const sources = [\n    cv.title,\n    cv.application_title,\n    cv.resume,\n    cv.skills,\n    cv.keywords,\n    cv.text_content,\n    cv.description,\n  ];'
);
fetchCode = fetchCode.replace('return combined.length >= 30;', 'return combined.length >= 10;');

let normCode = normNode.parameters.jsCode;
const normSources = /const sources = \[\s*cv\.text_content,\s*cv\.resume,\s*cv\.skills,\s*cv\.keywords,\s*cv\.description,\s*meta\.summary,\s*meta\.experience,\s*meta\.notes,\s*\]\.filter\(Boolean\);/m;
normCode = normCode.replace(
  normSources,
  'const sources = [\n    cv.title,\n    cv.application_title,\n    cv.text_content,\n    cv.resume,\n    cv.skills,\n    cv.keywords,\n    cv.description,\n    meta.summary,\n    meta.experience,\n    meta.notes,\n  ].filter(Boolean);'
);
normCode = normCode.replace('if (!email || text.length < 30) {', 'if (!email || text.length < 10) {');
normCode = normCode.replace(
  ".filter(cv => (cv.text_content || '').length >= 30);",
  ".filter(cv => (cv.text_content || '').length >= 10);"
);

if (fetchCode === fetchNode.parameters.jsCode) {
  throw new Error('Fetch All CVs unchanged');
}

if (normCode === normNode.parameters.jsCode) {
  throw new Error('Normalize Job + CV unchanged');
}

fetchNode.parameters.jsCode = fetchCode;
normNode.parameters.jsCode = normCode;

fs.writeFileSync(path, JSON.stringify(data, null, 2) + '\n', 'utf8');
