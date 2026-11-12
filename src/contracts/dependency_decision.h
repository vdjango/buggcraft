#ifndef BUGG_CONTRACTS_DEPENDENCY_DECISION_H_
#define BUGG_CONTRACTS_DEPENDENCY_DECISION_H_
#include <QVariantMap>
#include <stdexcept>

namespace bugg {
/// Worker result requiring a user choice; no staged files have been committed.
/// The application retains the original task spec and exact combination fingerprint.
class DependencyDecision : public std::runtime_error {
 public:
  explicit DependencyDecision(QVariantMap value)
      : std::runtime_error("dependency_decision_required"), value_(std::move(value)) {}
  const QVariantMap& value() const { return value_; }

 private:
  QVariantMap value_;
};
}  // namespace bugg
#endif
