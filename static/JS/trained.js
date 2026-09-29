document.addEventListener('DOMContentLoaded', function() {
    loadTrainedParts();

    document.getElementById('trainForm').addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const formData = new FormData(this);
        const loading = document.getElementById('loadingIndicator');
        const result = document.getElementById('resultArea');
        
        loading.classList.add('show');
        result.classList.remove('show');
        
        try {
            const response = await fetch('/api/train-edges', {
                method: 'POST',
                body: formData
            });
            
            const data = await response.json();
            loading.classList.remove('show');
            
            if (data.success) {
                document.getElementById('resultImage').src = data.visualization;
                
                const featuresHtml = `
                    <div class="feature-item">
                        <div class="feature-label">Area</div>
                        <div class="feature-value">${data.features.area.toFixed(0)}</div>
                    </div>
                    <div class="feature-item">
                        <div class="feature-label">Perimeter</div>
                        <div class="feature-value">${data.features.perimeter.toFixed(0)}</div>
                    </div>
                    <div class="feature-item">
                        <div class="feature-label">Aspect Ratio</div>
                        <div class="feature-value">${data.features.aspect_ratio.toFixed(2)}</div>
                    </div>
                    <div class="feature-item">
                        <div class="feature-label">Solidity</div>
                        <div class="feature-value">${data.features.solidity.toFixed(2)}</div>
                    </div>
                `;
                document.getElementById('featuresGrid').innerHTML = featuresHtml;
                result.classList.add('show');
                
                loadTrainedParts();
            } else {
                alert('Training failed: ' + data.error);
            }
        } catch (error) {
            loading.classList.remove('show');
            alert('Error: ' + error.message);
        }
    });
});

async function loadTrainedParts() {
    try {
        const response = await fetch('/api/trained-parts');
        const data = await response.json();
        
        const container = document.getElementById('trainedPartsList');
        
        if (data.parts && data.parts.length > 0) {
            container.innerHTML = data.parts.map(part => `
                <div class="part-item" onclick="viewPartEdges('${part.part_number}')">
                    <span class="part-number">${part.part_number}</span>
                    <span class="image-count">${part.image_count} images</span>
                </div>
            `).join('');
        } else {
            container.innerHTML = '<p>No trained parts yet. Upload a reference image to get started.</p>';
        }
    } catch (error) {
        console.error('Error loading parts:', error);
    }
}

async function viewPartEdges(partNumber) {
    try {
        const response = await fetch(`/api/view-edges/${partNumber}`);
        const data = await response.json();
        
        const container = document.getElementById('edgesPreview');
        
        if (data.images && data.images.length > 0) {
            container.innerHTML = `
                <h3>Edges for Part ${partNumber}</h3>
                <div class="edges-preview">
                    ${data.images.map(img => `
                        <div class="edge-image-container">
                            <img src="${img.edges}" alt="Edge detection">
                            <p>Edge Detection</p>
                        </div>
                    `).join('')}
                </div>
            `;
        } else {
            container.innerHTML = '<p>No edge data available for this part.</p>';
        }
    } catch (error) {
        console.error('Error viewing edges:', error);
    }
}
