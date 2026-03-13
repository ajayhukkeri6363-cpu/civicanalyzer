if (!window.chartColors) {
    window.chartColors = {
        Road: 'rgba(54, 162, 235, 0.8)',
        Water: 'rgba(75, 192, 192, 0.8)',
        Electricity: 'rgba(255, 206, 86, 0.8)',
        Garbage: 'rgba(255, 99, 132, 0.8)',
        Other: 'rgba(153, 102, 255, 0.8)',
        default: 'rgba(11, 46, 89, 0.8)' // primary-color
    };
}

function initAnalytics() {
    fetchAnalyticsData();
}

function fetchAnalyticsData() {
    fetch('/api/analytics')
        .then(response => {
            if (!response.ok) {
                throw new Error('Network response was not ok');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                console.error("API Error:", data.error);
                return;
            }
            
            updateStats(data);
            renderIssueTypeChart(data.by_issue); // Swapped to Bar
            renderAreaChart(data.by_area);       // Swapped to Pie
            renderTrendChart(data.trends);       // Line with tooltips
        })
        .catch(error => {
            console.error('Error fetching analytics data:', error);
        });
        
    fetch('/api/heatmap')
        .then(res => res.json())
        .then(data => {
            if(!data.error) renderHeatmap(data);
        });

    fetch('/api/insights')
        .then(res => res.json())
        .then(data => {
            if(!data.error) {
                renderPredictions(data.predictions);
                renderClusters(data.clusters);
                renderRecommendations(data.recommendations);
            }
        })
        .catch(err => console.error("Insights error:", err));
}

function updateStats(data) {
    document.getElementById('statTotal').textContent = data.total_complaints;
    document.getElementById('statResolved').textContent = data.resolved_complaints;
    
    const active = data.total_complaints - data.resolved_complaints;
    document.getElementById('statActive').textContent = active;
}

// Ensure charts object exists globally
window.charts = window.charts || {};

function renderIssueTypeChart(issueData) {
    const ctx = document.getElementById('issueTypeChart');
    if (!ctx) return;
    
    if (window.charts.issueType) window.charts.issueType.destroy();
    
    if (!issueData || issueData.length === 0) return;
    
    const labels = issueData.map(item => item.issue_type);
    const data = issueData.map(item => item.count);
    const backgroundColors = labels.map(label => window.chartColors[label] || window.chartColors.default);
    
    // Per requirement: Bar chart for most common issues
    window.charts.issueType = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Complaints',
                data: data,
                backgroundColor: backgroundColors,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 } }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(11, 46, 89, 0.9)',
                    padding: 12,
                    titleFont: { size: 14 },
                    bodyFont: { size: 13 },
                    callbacks: {
                        label: function(context) { return ` ${context.parsed.y} complaints reported`; }
                    }
                }
            },
            interaction: { mode: 'index', intersect: false }
        }
    });
}

function renderAreaChart(areaData) {
    const ctx = document.getElementById('areaChart');
    if (!ctx) return;
    
    if (window.charts.area) window.charts.area.destroy();
    
    if (!areaData || areaData.length === 0) return;
    
    const labels = areaData.map(item => item.area);
    const data = areaData.map(item => item.count);
    
    // Auto-generate colors for pie slices since areas are dynamic
    const bgColors = labels.map((_, i) => `hsl(${(i * 360) / labels.length}, 70%, 50%)`);
    
    // Per requirement: Pie chart for complaints by area
    window.charts.area = new Chart(ctx, {
        type: 'doughnut', // Doughnut is generally cleaner than pure pie
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: bgColors,
                borderWidth: 2,
                hoverOffset: 10
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'right' },
                tooltip: {
                    backgroundColor: 'rgba(11, 46, 89, 0.9)',
                    callbacks: {
                        label: function(context) {
                            const total = context.dataset.data.reduce((a,b) => a+b, 0);
                            const percent = Math.round((context.parsed / total) * 100);
                            return ` ${context.parsed} complaints (${percent}%)`;
                        }
                    }
                }
            }
        }
    });
}

function renderTrendChart(trendData) {
    const ctx = document.getElementById('trendChart');
    if (!ctx) return;
    
    if (window.charts.trend) window.charts.trend.destroy();
    
    if (!trendData || trendData.length === 0) return;
    
    const labels = trendData.map(item => item.month); // Assuming YYYY-MM
    const data = trendData.map(item => item.count);
    
    window.charts.trend = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Volume',
                id: 'trendDataset',
                data: data,
                borderColor: window.chartColors.default,
                backgroundColor: 'rgba(11, 46, 89, 0.1)',
                borderWidth: 3,
                fill: true,
                tension: 0.4, // smooth curves
                pointBackgroundColor: window.chartColors.default,
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { beginAtZero: true, ticks: { precision: 0 } }
            },
            plugins: {
                tooltip: {
                    backgroundColor: 'rgba(11, 46, 89, 0.9)',
                    mode: 'index',
                    intersect: false
                }
            },
            interaction: { mode: 'nearest', axis: 'x', intersect: false }
        }
    });
}

function renderHeatmap(areaData) {
    const container = document.getElementById('issueMap');
    if(!container) return;
    
    if(window.heatmap) {
        window.heatmap.remove();
        window.heatmap = null;
    }
    
    // Default center
    const map = L.map('issueMap').setView([37.7749, -122.4194], 12);
    window.heatmap = map;
    
    // Add OpenStreetMap tiles
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);
    
    const markers = [];
    areaData.forEach(area => {
        let color = '#27ae60'; // Green (<5)
        if(area.volume >= 10) color = '#c0392b'; // Red
        else if(area.volume >= 5) color = '#f39c12'; // Yellow
        
        const radius = Math.min(200 + (area.volume * 50), 1000); // meters
        
        const circle = L.circle(area.coords, {
            color: color,
            fillColor: color,
            fillOpacity: 0.6,
            radius: radius
        }).addTo(map)
        .bindPopup(`<b>${area.area}</b><br>${area.volume} Complaints Reported`);
        
        markers.push(circle);
    });

    if (markers.length > 0) {
        const group = new L.featureGroup(markers);
        map.fitBounds(group.getBounds().pad(0.5));
    }

    setTimeout(() => { map.invalidateSize(); }, 200);
}

function renderPredictions(predictions) {
    const list = document.getElementById('predictionList');
    if (!list) return;
    
    if (!predictions || predictions.length === 0) {
        list.innerHTML = '<p class="text-muted">No high-risk areas predicted for the next 7 days.</p>';
        return;
    }
    
    list.innerHTML = predictions.map(p => `
        <div class="insight-item">
            <div>
                <strong>${p.area}</strong>
                <div style="font-size: 0.8rem; color: var(--text-muted)">Volume: ${p.recent_volume} | Growth: +${p.growth}%</div>
            </div>
            <span class="risk-badge ${p.risk_level === 'Critical' ? 'risk-critical' : 'risk-high'}">${p.risk_level}</span>
        </div>
    `).join('');
}

function renderClusters(clusters) {
    const list = document.getElementById('clusterList');
    if (!list) return;
    
    if (!clusters || clusters.length === 0) {
        list.innerHTML = '<p class="text-muted">No major issue clusters detected.</p>';
        return;
    }
    
    list.innerHTML = clusters.map(c => `
        <div class="insight-item">
            <div>
                <i class="fa-solid fa-location-dot" style="color: var(--secondary-color)"></i> 
                <strong>${c.area}</strong> - ${c.issue_type}
            </div>
            <span class="cluster-badge">${c.count} items</span>
        </div>
    `).join('');
}

function renderRecommendations(recommendations) {
    const list = document.getElementById('recommendationList');
    if (!list) return;
    
    if (!recommendations || recommendations.length === 0) {
        list.innerHTML = '<p class="text-muted">Insufficient data to generate recommendations.</p>';
        return;
    }
    
    const icons = {
        'Garbage': 'fa-trash-can',
        'Road': 'fa-road',
        'Water': 'fa-droplet',
        'Electricity': 'fa-bolt',
        'default': 'fa-circle-info'
    };
    
    list.innerHTML = recommendations.map(r => `
        <div class="rec-card">
            <div class="rec-icon">
                <i class="fa-solid ${icons[r.issue] || icons.default}"></i>
            </div>
            <div class="rec-content">
                <div class="rec-tag">${r.action}</div>
                <h4>${r.issue} Issue - ${r.area}</h4>
                <p>${r.suggestion}</p>
            </div>
        </div>
    `).join('');
}

// Define globally but don't auto-init here (handled by main.js)
window.initAnalytics = initAnalytics;
window.fetchAnalyticsData = fetchAnalyticsData; // Support refresh button
