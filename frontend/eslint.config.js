// ESLint 9 flat config (the old .eslintrc format is no longer read).
import js from '@eslint/js';
import globals from 'globals';
import react from 'eslint-plugin-react';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import prettier from 'eslint-config-prettier';

export default [
  { ignores: ['dist/**', 'coverage/**', 'public/**', 'node_modules/**'] },
  js.configs.recommended,
  react.configs.flat.recommended,
  react.configs.flat['jsx-runtime'],
  {
    files: ['**/*.{js,jsx}'],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: { ...globals.browser },
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    settings: { react: { version: 'detect' } },
    plugins: { 'react-hooks': reactHooks, 'react-refresh': reactRefresh },
    rules: {
      // classic hook rules only; the React Compiler rules of react-hooks v7 do not apply (no compiler here)
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      // several components export helpers on purpose (unit-tested); only affects Vite HMR granularity
      'react-refresh/only-export-components': 'off',
      'react/prop-types': 'off',
      // react-three-fiber intrinsic elements take Three.js object properties as props
      'react/no-unknown-property': ['error', { ignore: [
        'args', 'attach', 'castShadow', 'receiveShadow', 'depthWrite', 'depthTest', 'geometry', 'material',
        'groundColor', 'skyColor', 'intensity', 'metalness', 'roughness', 'object', 'dispose', 'position',
        'rotation', 'scale', 'side', 'transparent', 'opacity', 'vertexColors', 'wireframe', 'onPointerMissed',
        'shadow-camera-bottom', 'shadow-camera-far', 'shadow-camera-left', 'shadow-camera-right',
        'shadow-camera-top', 'shadow-mapSize-height', 'shadow-mapSize-width', 'flatShading', 'toneMapped',
      ] }],
      // `import React` is unnecessary with the automatic JSX runtime but harmless
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^(_|React$)', ignoreRestSiblings: true }],
    },
  },
  {
    files: ['**/*.test.{js,jsx}', 'src/test/**', 'vite.config.js', 'vitest.config.js', 'eslint.config.js'],
    languageOptions: { globals: { ...globals.node, ...globals.vitest } },
  },
  prettier,
];
