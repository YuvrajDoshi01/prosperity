const fs = require('fs');
const path = require('path');

const KNOWLEDGE_DIR = '/home/mmaliar/.gemini/antigravity/knowledge';

function getKIs() {
  if (!fs.existsSync(KNOWLEDGE_DIR)) {
    console.log("KNOWLEDGE_DIR not found.");
    return [];
  }
  return fs.readdirSync(KNOWLEDGE_DIR).filter(sub => {
    return fs.statSync(path.join(KNOWLEDGE_DIR, sub)).isDirectory();
  });
}

const kis = getKIs();
console.log(`Found ${kis.length} KIs`);
for (const ki of kis) {
    const metaPath = path.join(KNOWLEDGE_DIR, ki, 'metadata.json');
    if (fs.existsSync(metaPath)) {
        console.log(`\n\n--- ${ki} ---`);
        console.log(fs.readFileSync(metaPath, 'utf8'));
    }
}
