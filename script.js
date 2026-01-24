// DOM Elements
const mediaForm = document.getElementById('mediaForm');
const urlInput = document.getElementById('urlInput');
const analyzeBtn = document.getElementById('analyzeBtn');
const outputSection = document.getElementById('outputSection');
const outputContent = document.getElementById('outputContent');
const copyBtn = document.getElementById('copyBtn');
const loadingOverlay = document.getElementById('loadingOverlay');
const exampleButtons = document.querySelectorAll('.example-btn');

// API Base URL - Update this if your API is hosted elsewhere
const API_BASE_URL = window.location.origin;

// State
let currentOutput = '';

// Event Listeners
mediaForm.addEventListener('submit', handleFormSubmit);
copyBtn.addEventListener('click', handleCopy);

exampleButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        const exampleUrl = btn.getAttribute('data-url');
        urlInput.value = exampleUrl;
        urlInput.focus();
    });
});

// Form Submit Handler
async function handleFormSubmit(e) {
    e.preventDefault();
    
    const url = urlInput.value.trim();
    if (!url) {
        showError('Please enter a valid URL');
        return;
    }
    
    const format = document.querySelector('input[name="format"]:checked').value;
    
    await analyzeMedia(url, format);
}

// Analyze Media
async function analyzeMedia(url, format) {
    try {
        // Show loading state
        showLoading(true);
        hideOutput();
        
        // Build API URL
        const apiUrl = `${API_BASE_URL}/?url=${encodeURIComponent(url)}&format=${format}`;
        
        // Make API request
        const response = await fetch(apiUrl);
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to analyze media');
        }
        
        // Get response based on format
        if (format === 'json') {
            const data = await response.json();
            currentOutput = JSON.stringify(data, null, 2);
            displayOutput(currentOutput, 'json');
        } else {
            const data = await response.text();
            currentOutput = data;
            displayOutput(data, 'text');
        }
        
        showOutput();
        
    } catch (error) {
        console.error('Analysis error:', error);
        showError(error.message || 'An error occurred while analyzing the media');
    } finally {
        showLoading(false);
    }
}

// Display Output
function displayOutput(content, type) {
    if (type === 'json') {
        outputContent.innerHTML = `<div class="json-content">${escapeHtml(content)}</div>`;
    } else {
        outputContent.textContent = content;
    }
}

// Show/Hide Output Section
function showOutput() {
    outputSection.classList.remove('hidden');
    outputSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideOutput() {
    outputSection.classList.add('hidden');
}

// Show/Hide Loading
function showLoading(show) {
    if (show) {
        loadingOverlay.classList.remove('hidden');
        analyzeBtn.classList.add('loading');
        analyzeBtn.disabled = true;
    } else {
        loadingOverlay.classList.add('hidden');
        analyzeBtn.classList.remove('loading');
        analyzeBtn.disabled = false;
    }
}

// Copy to Clipboard
async function handleCopy() {
    try {
        await navigator.clipboard.writeText(currentOutput);
        
        // Visual feedback
        const originalText = copyBtn.querySelector('.btn-text').textContent;
        copyBtn.querySelector('.btn-text').textContent = 'Copied!';
        copyBtn.style.background = 'var(--gradient-primary)';
        copyBtn.style.color = 'white';
        
        setTimeout(() => {
            copyBtn.querySelector('.btn-text').textContent = originalText;
            copyBtn.style.background = '';
            copyBtn.style.color = '';
        }, 2000);
        
    } catch (error) {
        console.error('Copy failed:', error);
        showError('Failed to copy to clipboard');
    }
}

// Show Error Message
function showError(message) {
    // Create error notification
    const errorDiv = document.createElement('div');
    errorDiv.className = 'error-notification';
    errorDiv.textContent = message;
    errorDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: linear-gradient(135deg, hsl(0, 84%, 60%) 0%, hsl(15, 84%, 50%) 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 12px;
        box-shadow: 0 4px 16px hsla(0, 84%, 30%, 0.4);
        z-index: 2000;
        animation: slideInRight 0.3s ease-out;
        max-width: 400px;
        font-weight: 500;
    `;
    
    document.body.appendChild(errorDiv);
    
    // Remove after 5 seconds
    setTimeout(() => {
        errorDiv.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => errorDiv.remove(), 300);
    }, 5000);
}

// Utility: Escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Add error notification animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// URL Validation on Input
urlInput.addEventListener('input', (e) => {
    const value = e.target.value.trim();
    
    if (value && !isValidUrl(value)) {
        urlInput.style.borderColor = 'hsl(0, 84%, 60%)';
    } else {
        urlInput.style.borderColor = '';
    }
});

// Validate URL Format
function isValidUrl(string) {
    try {
        new URL(string);
        return true;
    } catch (_) {
        return false;
    }
}

// Keyboard Shortcuts
document.addEventListener('keydown', (e) => {
    // Ctrl/Cmd + Enter to submit form
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        if (!analyzeBtn.disabled) {
            mediaForm.dispatchEvent(new Event('submit'));
        }
    }
    
    // Ctrl/Cmd + C to copy when output is visible
    if ((e.ctrlKey || e.metaKey) && e.key === 'c' && !outputSection.classList.contains('hidden')) {
        if (!document.getSelection().toString()) {
            e.preventDefault();
            handleCopy();
        }
    }
});

// Auto-focus input on page load
window.addEventListener('load', () => {
    urlInput.focus();
});
