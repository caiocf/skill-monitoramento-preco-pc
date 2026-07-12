#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

function resolveTargetDir() {
  const envTarget = process.env.SKILL_TARGET_DIR;
  if (envTarget) return envTarget;

  const home = process.env.HOME || process.env.USERPROFILE || process.cwd();
  const candidates = [
    path.join(home, '.agents', 'skills'),
    path.join(home, '.codex', 'skills'),
    path.join(home, '.claude', 'skills'),
    path.join(process.cwd(), 'installed-skills')
  ];

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return path.join(home, '.agents', 'skills');
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (shouldSkip(entry.name)) {
      continue;
    }
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function shouldSkip(name) {
  return [
    '.git',
    '.github',
    '.pytest_cache',
    '.venv',
    '__pycache__',
    'node_modules',
    'output',
  ].includes(name) || name.endsWith('.pyc');
}

const root = path.resolve(__dirname, '..');
const targetRoot = resolveTargetDir();
const targetDir = path.join(targetRoot, 'comparador-precos-pc-br');

fs.mkdirSync(targetRoot, { recursive: true });
copyDir(root, targetDir);

console.log(`Skill instalada em: ${targetDir}`);
console.log('Agora reinicie o agente hospedeiro e use a skill pelo nome registrado em SKILL.md.');
