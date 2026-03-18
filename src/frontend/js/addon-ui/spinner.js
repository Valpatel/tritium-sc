// Created by Matthew Valancy
// Copyright 2026 Valpatel Software LLC
// Licensed under AGPL-3.0 — see LICENSE for details.
//
// spinner.js -- shared loading spinner for addon panels.

const SPINNER_CLASS = 'addon-spinner';

/**
 * Show a loading spinner inside a container element.
 * @param {HTMLElement} container
 * @param {string} [text='Loading...']
 */
function showSpinner(container, text = 'Loading...') {
    // Remove any existing spinner first
    hideSpinner(container);

    const wrapper = document.createElement('div');
    wrapper.classList.add(SPINNER_CLASS);

    const ring = document.createElement('div');
    ring.classList.add('addon-spinner-ring');
    wrapper.appendChild(ring);

    const label = document.createElement('div');
    label.classList.add('addon-spinner-text');
    label.textContent = text;
    wrapper.appendChild(label);

    container.appendChild(wrapper);
}

/**
 * Remove the loading spinner from a container element.
 * @param {HTMLElement} container
 */
function hideSpinner(container) {
    const existing = container.querySelector('.' + SPINNER_CLASS);
    if (existing) {
        existing.parentNode.removeChild(existing);
    }
}

export { showSpinner, hideSpinner };
