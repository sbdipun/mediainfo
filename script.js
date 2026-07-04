// DOM Elements
const mediaForm = document.getElementById('mediaForm');
const urlInput = document.getElementById('urlInput');
const analyzeBtn = document.getElementById('analyzeBtn');
const outputSection = document.getElementById('outputSection');
const outputContent = document.getElementById('outputContent');
const copyBtn = document.getElementById('copyBtn');
const loadingOverlay = document.getElementById('loadingOverlay');
const exampleButtons = document.querySelectorAll('.example-btn');

const compareForm = document.getElementById('compareForm');
const compareUrl1 = document.getElementById('compareUrl1');
const compareUrl2 = document.getElementById('compareUrl2');
const compareCount = document.getElementById('compareCount');
const compareBtn = document.getElementById('compareBtn');
const compareOutputSection = document.getElementById('compareOutputSection');
const compareOutputContent = document.getElementById('compareOutputContent');

// API Base URL - Update this if your API is hosted elsewhere
const API_BASE_URL = window.location.origin;

// State
let currentOutput = '';
let compareData = null;
let compareIndex = 0;

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

compareForm.addEventListener('submit', handleCompareSubmit);

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

async function handleCompareSubmit(e) {
    e.preventDefault();

    const url1 = compareUrl1.value.trim();
    const url2 = compareUrl2.value.trim();
    const count = parseInt(compareCount.value, 10) || 3;

    if (!url1 || !url2) {
        showError('Please enter both source URLs for comparison');
        return;
    }

    if (count < 1 || count > 8) {
        showError('Please choose between 1 and 8 snapshots');
        return;
    }

    await compareThumbnails(url1, url2, count);
}

// Compare Thumbnails
async function compareThumbnails(url1, url2, count) {
    try {
        showLoading(true);
        hideCompareOutput();
        hideOutput();

        const query = new URLSearchParams({
            url1: url1,
            url2: url2,
            count: count.toString()
        });

        const response = await fetch(`${API_BASE_URL}/compare-thumbnails?${query.toString()}`);
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to compare thumbnails');
        }

        const data = await response.json();
        compareData = data;
        compareIndex = 0;
        displayCompareOutput(data);
        showCompareOutput();
    } catch (error) {
        console.error('Compare error:', error);
        showError(error.message || 'An error occurred while comparing thumbnails');
    } finally {
        showLoading(false);
    }
}

function displayCompareOutput(data) {
    if (!data || !data.sources || !Array.isArray(data.sources) || data.sources.length < 2) {
        compareOutputContent.innerHTML = '<p>No thumbnails were returned for comparison.</p>';
        return;
    }

    const slideCount = data.count || data.sources[0].thumbnails.length;
    const slides = [];

    for (let index = 0; index < slideCount; index++) {
        const slideSources = data.sources.map((source, sourceIndex) => {
            const thumbnail = source.thumbnails[index] || '';
            return `
                <div class="compare-source">
                    <div class="compare-source-title">Source ${sourceIndex + 1}</div>
                    <div class="compare-source-url">${escapeHtml(source.url)}</div>
                    <img src="${thumbnail}" alt="Thumbnail ${index + 1} from source ${sourceIndex + 1}">
                </div>
            `;
        }).join('');

        slides.push(`
            <div class="compare-slide" data-index="${index}">
                ${slideSources}
            </div>
        `);
    }

    compareOutputContent.innerHTML = `
        <div class="compare-carousel">
            ${slides.join('')}
        </div>
        <div class="compare-controls">
            <button type="button" id="comparePrev" class="btn btn-secondary compare-btn">Previous</button>
            <span class="compare-progress">Slide <span id="compareSlideIndex">1</span> of ${slideCount}</span>
            <button type="button" id="compareNext" class="btn btn-secondary compare-btn">Next</button>
        </div>
    `;

    document.getElementById('comparePrev').addEventListener('click', () => setCompareSlide(compareIndex - 1));
    document.getElementById('compareNext').addEventListener('click', () => setCompareSlide(compareIndex + 1));

    setCompareSlide(0);
}

function setCompareSlide(index) {
    if (!compareData || !compareData.sources) {
        return;
    }

    const slideCount = compareData.count || compareData.sources[0].thumbnails.length;
    if (index < 0) {
        index = slideCount - 1;
    } else if (index >= slideCount) {
        index = 0;
    }

    compareIndex = index;
    const slides = compareOutputContent.querySelectorAll('.compare-slide');
    slides.forEach(slide => {
        slide.classList.toggle('active', Number(slide.getAttribute('data-index')) === index);
    });

    const progress = compareOutputContent.querySelector('#compareSlideIndex');
    if (progress) {
        progress.textContent = index + 1;
    }
}

function showCompareOutput() {
    compareOutputSection.classList.remove('hidden');
    compareOutputSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideCompareOutput() {
    compareOutputSection.classList.add('hidden');
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
        if (compareBtn) {
            compareBtn.disabled = true;
        }
    } else {
        loadingOverlay.classList.add('hidden');
        analyzeBtn.classList.remove('loading');
        analyzeBtn.disabled = false;
        if (compareBtn) {
            compareBtn.disabled = false;
        }
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
